"""Verified inference-only loader for the frozen research release."""
import hashlib
import json
from pathlib import Path

LOCK = Path(__file__).with_name('frozen-model.json')


def verify_adapter(adapter_path):
    lock = json.loads(LOCK.read_text())
    for name, expected in lock['adapter_files_sha256'].items():
        path = Path(adapter_path) / name
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f'Frozen release checksum mismatch: {name}')
    return lock


def load_frozen(adapter_path, device='cuda'):
    import torch
    from transformers import AutoTokenizer, AutoModelForSequenceClassification
    from peft import PeftModel
    lock = verify_adapter(adapter_path)
    tokenizer = AutoTokenizer.from_pretrained(adapter_path)
    tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = 'right'
    base = AutoModelForSequenceClassification.from_pretrained(
        lock['base_model'], revision=lock['base_revision'], num_labels=1,
        torch_dtype=torch.bfloat16, attn_implementation='sdpa')
    base.config.pad_token_id = tokenizer.pad_token_id
    base.config.use_cache = False
    model = PeftModel.from_pretrained(base, adapter_path, is_trainable=False)
    model.requires_grad_(False)
    model.to(device).eval()
    return model, tokenizer, lock['calibration']
