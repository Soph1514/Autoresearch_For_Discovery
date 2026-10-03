"""Fixed-input OOD audit of initialization and saved adapter; never trains."""
import hashlib
import json
from pathlib import Path
import modal

HERE = Path(__file__).parent
RUN = 'run-20261003T192204Z'
image = (modal.Image.debian_slim(python_version='3.11')
    .pip_install('torch==2.7.1', 'transformers==4.56.2', 'peft==0.17.1',
                 'accelerate==1.10.1', 'datasets==4.1.1', 'scikit-learn==1.7.2',
                 'matplotlib==3.10.6')
    .add_local_file(HERE/'experiment.py', '/root/experiment.py')
    .add_local_dir(HERE/'artifacts/ood-v1', '/root/ood'))
volume = modal.Volume.from_name('lean-fidelity-research')
app = modal.App('lean-fidelity-ood-audit')

@app.function(image=image, gpu='A100-80GB', cpu=(2,4), memory=(16384,32768),
              timeout=900, retries=0, max_containers=1, scaledown_window=2,
              volumes={'/artifacts':volume})
def audit():
    import time
    import torch
    from transformers import AutoTokenizer, AutoModelForSequenceClassification, set_seed
    from peft import get_peft_model, LoraConfig, TaskType
    from experiment import MODEL
    out=Path('/artifacts')/RUN
    manifest=json.loads((out/'manifest.json').read_text())
    data=Path('/root/ood/rows.json').read_bytes()
    provenance=json.loads(Path('/root/ood/manifest.json').read_text())
    assert hashlib.sha256(data).hexdigest()==provenance['rows_sha256']
    assert hashlib.sha256((out/'adapter/adapter_model.safetensors').read_bytes()).hexdigest()=='8665b2a6d47aab60521b56f7bcde6ef54aefa5b4c05b843d23c92346bca6b1f6'
    rows=json.loads(data)
    set_seed(42)
    tok=AutoTokenizer.from_pretrained(MODEL,revision=manifest['model_revision'])
    tok.pad_token=tok.eos_token
    tok.padding_side='right'
    base=AutoModelForSequenceClassification.from_pretrained(MODEL,
        revision=manifest['model_revision'],num_labels=1,
        torch_dtype=torch.bfloat16,attn_implementation='sdpa')
    base.config.pad_token_id=tok.pad_token_id
    base.config.use_cache=False
    model=get_peft_model(base,LoraConfig(task_type=TaskType.SEQ_CLS,r=16,
        lora_alpha=32,lora_dropout=.05,target_modules=['q_proj','v_proj'],
        modules_to_save=['score'])).cuda().eval()
    result={'run_id':RUN,'model':MODEL,'model_revision':manifest['model_revision'],
        'provenance':provenance,'baseline':'Reconstructed seed-42 random binary head on pretrained Qwen; not prompted Qwen.',
        'predictions':{},'batch_size':8,'threshold':.5}
    start=time.time()
    for variant in ('unfine_tuned','fine_tuned'):
        if variant=='fine_tuned':
            model.load_adapter(str(out/'adapter'),adapter_name='trained')
            model.set_adapter('trained')
            model.eval()
        predictions=[]
        with torch.inference_mode():
            for i in range(0,len(rows),8):
                part=rows[i:i+8]
                batch=tok([r['text'] for r in part],padding=True,truncation=False,return_tensors='pt').to('cuda')
                assert batch['input_ids'].shape[1]<=4096
                logits=model(**batch).logits.float().view(-1).cpu().tolist()
                predictions.extend({k:r[k] for k in ('id','group','dataset','source','label')} | {'logit':z,'predicted':int(z>=0)} for r,z in zip(part,logits))
        result['predictions'][variant]=predictions
        print(variant,len(predictions),'scored',flush=True)
    result['inference_seconds']=time.time()-start
    (out/'ood_audit.json').write_text(json.dumps(result,indent=2))
    volume.commit()
    return result

@app.local_entrypoint()
def main():
    call=audit.spawn()
    try:
        result=call.get(timeout=900)
    except BaseException:
        call.cancel(terminate_containers=True)
        raise
    (HERE/'artifacts'/RUN/'ood_audit.json').write_text(json.dumps(result,indent=2)+'\n')
    print('Saved OOD predictions; run summarize_ood.py for tables and plots.')
