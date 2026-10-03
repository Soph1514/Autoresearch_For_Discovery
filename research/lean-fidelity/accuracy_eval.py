"""Post-run accuracy audit. No optimizer updates or threshold fitting."""
import json
from pathlib import Path
import modal
image = (modal.Image.debian_slim(python_version="3.11")
         .pip_install("torch==2.7.1", "transformers==4.56.2", "peft==0.17.1",
                      "accelerate==1.10.1", "datasets==4.1.1", "scikit-learn==1.7.2",
                      "matplotlib==3.10.6")
         .add_local_file(Path(__file__).parent / "experiment.py", "/root/experiment.py"))
volume = modal.Volume.from_name("lean-fidelity-research")

HERE = Path(__file__).parent
RUN = 'run-20261003T192204Z'
app = modal.App('lean-fidelity-accuracy-audit')

@app.function(image=image, gpu='A100-80GB', cpu=(2, 4), memory=(16384, 32768),
              timeout=900, retries=0, max_containers=1, scaledown_window=2,
              volumes={'/artifacts': volume})
def audit():
    import sys
    import time
    import torch
    from transformers import AutoTokenizer, AutoModelForSequenceClassification, set_seed
    from peft import get_peft_model, LoraConfig, TaskType
    sys.path.insert(0, '/root')
    from experiment import MODEL, load_rows
    out = Path('/artifacts') / RUN
    manifest = json.loads((out / 'manifest.json').read_text())
    set_seed(42)
    tok = AutoTokenizer.from_pretrained(MODEL, revision=manifest['model_revision'])
    tok.pad_token = tok.eos_token
    tok.padding_side = 'right'
    base = AutoModelForSequenceClassification.from_pretrained(
        MODEL, revision=manifest['model_revision'], num_labels=1,
        torch_dtype=torch.bfloat16, attn_implementation='sdpa')
    base.config.pad_token_id = tok.pad_token_id
    base.config.use_cache = False
    model = get_peft_model(base, LoraConfig(task_type=TaskType.SEQ_CLS,
        r=16, lora_alpha=32, lora_dropout=.05, target_modules=['q_proj','v_proj'],
        modules_to_save=['score'])).cuda().eval()
    results = {'model': MODEL, 'run_id': RUN, 'threshold_probability': .5,
        'seed': 42, 'baseline': 'Recreated original initialization: pretrained backbone, random binary head, zero-effect initial LoRA. Not a prompted baseline.',
        'initialization_note': 'Reconstructed with the original revision, seed, dtype and initialization recipe; no pre-training checkpoint was saved.',
        'results': [], 'predictions': {}}
    started = time.time()
    for variant in ('unfine_tuned', 'fine_tuned'):
        if variant == 'fine_tuned':
            model.load_adapter(str(out / 'adapter'), adapter_name='trained')
            model.set_adapter('trained')
            model.eval()
        for split in ('train', 'test'):
            rows = load_rows(out, split)
            predictions = []
            with torch.inference_mode():
                for i in range(0, len(rows), 8):
                    part = rows[i:i+8]
                    batch = tok([r['text'] for r in part], padding=True,
                                truncation=False, return_tensors='pt').to('cuda')
                    logits = model(**batch).logits.float().view(-1).cpu().tolist()
                    predictions.extend({'id':r['id'], 'label':r['label'], 'logit':z,
                                        'predicted':int(z>=0)} for r,z in zip(part,logits))
            correct = sum(p['label']==p['predicted'] for p in predictions)
            entry = {'model':variant, 'split':split, 'correct':correct,
                     'total':len(rows), 'accuracy':correct/len(rows)}
            results['results'].append(entry)
            results['predictions'][variant+'_'+split] = predictions
            print(json.dumps(entry), flush=True)
    # Confirm batched inference agrees closely with original single-example evaluation.
    original = json.loads((out/'test_predictions.json').read_text())
    current = results['predictions']['fine_tuned_test']
    assert len(original) == len(current)
    assert all(a['id'] == b['id'] and a['label'] == b['label'] for a,b in zip(original,current))
    results['test_prediction_disagreements_vs_original'] = sum(
        int(a['p_faithful'] >= .5) != b['predicted'] for a,b in zip(original,current))
    results['evaluation_seconds'] = time.time()-started
    (out/'accuracy_audit.json').write_text(json.dumps(results,indent=2))
    volume.commit()
    return results

@app.local_entrypoint()
def main():
    call = audit.spawn()
    try:
        result = call.get(timeout=900)
    except BaseException:
        call.cancel(terminate_containers=True)
        raise
    target = HERE/'artifacts'/RUN/'accuracy_audit.json'
    target.write_text(json.dumps(result,indent=2)+'\n')
    result.pop('predictions')
    (HERE/'reports'/'accuracy-comparison.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
