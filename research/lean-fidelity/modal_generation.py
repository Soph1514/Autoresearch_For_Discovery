"""Hosted Qwen generation and isolated, pinned Lean checking (no training)."""
from pathlib import Path
import modal

app = modal.App('lean-generation')
MODEL = 'Qwen/Qwen3-4B-Instruct-2507'
REVISION = 'cdbee75f17c01a7cc42f958dc650907174af0554'
gpu_image = modal.Image.debian_slim(python_version='3.11').pip_install(
    'torch==2.7.1', 'transformers==4.56.2', 'accelerate==1.10.1')
cache = modal.Volume.from_name('lean-generation-cache', create_if_missing=True)

@app.cls(image=gpu_image, gpu='A100-80GB', timeout=300, startup_timeout=600,
         min_containers=0, max_containers=1, scaledown_window=60,
         volumes={'/cache': cache})
class Generator:
    @modal.enter()
    def load(self):
        import torch
        from transformers import AutoTokenizer, AutoModelForCausalLM
        self.tokenizer = AutoTokenizer.from_pretrained(MODEL, revision=REVISION, cache_dir='/cache')
        self.model = AutoModelForCausalLM.from_pretrained(
            MODEL, revision=REVISION, cache_dir='/cache', torch_dtype=torch.bfloat16,
            device_map='auto').eval()

    @modal.method()
    def generate(self, problem: str, feedback: str = '') -> str:
        import torch
        messages = [
            {'role': 'system', 'content': 'Translate the problem into a complete Lean 4.19 file using Mathlib. Return only Lean code. Preserve the objective and all constraints. Do not use sorry, admit, custom axioms, or executable IO. For optimization problems define the problem and feasibility predicate; do not invent a theorem claiming an unproved solution.'},
            {'role': 'user', 'content': problem + ('\nPrevious checker feedback:\n' + feedback if feedback else '')}]
        text = self.tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        batch = self.tokenizer(text, return_tensors='pt').to(self.model.device)
        if batch.input_ids.shape[1] > 10000:
            raise ValueError('Problem exceeds generation context limit')
        with torch.inference_mode():
            output = self.model.generate(**batch, max_new_tokens=3000, do_sample=False,
                                         pad_token_id=self.tokenizer.eos_token_id)
        source = self.tokenizer.decode(output[0, batch.input_ids.shape[1]:], skip_special_tokens=True).strip()
        if source.startswith('```'):
            source = source.split('\n', 1)[1].rsplit('```', 1)[0].strip()
        return source
