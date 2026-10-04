"""Authenticated, scale-to-zero inference API for the frozen fidelity classifier."""
import hashlib
import json
from pathlib import Path
import modal

HERE = Path(__file__).parent
app = modal.App('lean-fidelity-api')
image = (modal.Image.debian_slim(python_version='3.11')
    .pip_install('torch==2.7.1', 'transformers==4.56.2', 'peft==0.17.1',
                 'accelerate==1.10.1', 'fastapi==0.115.12')
    .add_local_file(HERE/'frozen_model.py', '/root/frozen_model.py')
    .add_local_file(HERE/'frozen-model.json', '/root/frozen-model.json'))
volume = modal.Volume.from_name('lean-fidelity-research')


def validate(payload):
    if not isinstance(payload, dict):
        raise ValueError('Expected a JSON object.')
    fields = {}
    for key in ('problem', 'lean_context', 'candidate'):
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f'{key} must be a non-empty string.')
        if len(value) > 32000:
            raise ValueError(f'{key} exceeds the character limit.')
        fields[key] = value
    return fields


@app.cls(image=image, gpu='A100-80GB', cpu=(2,4), memory=(16384,32768),
         timeout=180, startup_timeout=600, min_containers=0, max_containers=1,
         scaledown_window=30, retries=0, volumes={'/artifacts':volume})
class Fidelity:
    @modal.enter()
    def load(self):
        from frozen_model import load_frozen
        self.lock = json.loads(Path('/root/frozen-model.json').read_text())
        adapter = Path('/artifacts')/self.lock['storage']['modal_path']
        self.model, self.tokenizer, self.calibration = load_frozen(adapter)

    @modal.method()
    def score(self, payload: dict):
        import torch
        fields = validate(payload)
        # Match the training input format; never apply a chat template here.
        text = (f"<problem>\n{fields['problem']}\n</problem>\n"
                f"<lean_context>\n{fields['lean_context']}\n</lean_context>\n"
                f"<candidate>\n{fields['candidate']}\n</candidate>\nFaithfulness:")
        batch = self.tokenizer(text, truncation=False, return_tensors='pt')
        result = {'model_version': self.lock['release'],
                  'specification_hash': hashlib.sha256(json.dumps(fields,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),
                  'raw_logit': None, 'p_faithful': None,
                  'fidelity_decision': 'review', 'reason_code': 'context_overflow',
                  'lean_checked': False,
                  'accept_threshold': self.calibration['accept_threshold']}
        if batch['input_ids'].shape[1] > 4096:
            return result
        with torch.inference_mode():
            logit = self.model(**batch.to('cuda')).logits.float().item()
            p = torch.sigmoid(torch.tensor(logit)/self.calibration['temperature']).item()
        accept = p >= self.calibration['accept_threshold']
        result.update(raw_logit=logit, p_faithful=p,
                      fidelity_decision='accept' if accept else 'review',
                      reason_code='high_alignment' if accept else 'uncertain_alignment')
        return result


# Authentication and input validation happen before starting a GPU container.
@app.function(image=image, timeout=240, min_containers=0, max_containers=2)
@modal.fastapi_endpoint(method='POST', requires_proxy_auth=True)
def score(payload: dict):
    from fastapi import HTTPException
    try:
        fields = validate(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return Fidelity().score.remote(fields)


@app.local_entrypoint()
def check():
    # One previously evaluated held-out example; this performs no training.
    result = Fidelity().score.remote({
        'problem': 'A ring $R$ is called a Boolean ring if $a^{2}=a$ for all $a \\in R$. Prove that every Boolean ring is commutative.',
        'lean_context': 'import Mathlib\n\nopen Fintype Subgroup Set Polynomial Ideal\nopen scoped BigOperators\n\n',
        'candidate': 'theorem dummy {R : Type*} [Ring R] (h : ∀ a : R, a ^ 2 = a) : ∀ a b : R, a * b = b * a'})
    assert abs(result['p_faithful']-.8742332458496094) < .02, result
    assert result['fidelity_decision']=='accept' and result['lean_checked'] is False
    print(json.dumps(result,indent=2))
