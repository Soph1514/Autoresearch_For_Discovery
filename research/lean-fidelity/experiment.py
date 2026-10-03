"""Small offline fidelity experiment. No work happens on import."""
import argparse
import hashlib
import json
import random
import re
from collections import Counter
from pathlib import Path

MODEL = "Qwen/Qwen3-4B-Instruct-2507"
DATA = "PAug/ProofNetVerif"


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + "\n")


def partition(rows, seed=42):
    # Join exact normalized English duplicates even if their source IDs differ.
    parent = {}
    def root(x):
        parent.setdefault(x, x)
        if parent[x] != x:
            parent[x] = root(parent[x])
        return parent[x]
    seen = {}
    for row in rows:
        key = " ".join(row["nl_statement"].split()).casefold()
        rid = row["id"]
        if key in seen:
            parent[root(rid)] = root(seen[key])
        seen[key] = rid
    groups = sorted({root(row["id"]) for row in rows})
    random.Random(seed).shuffle(groups)
    n = len(groups)
    pool = int(.8 * n)
    reserve = max(1, int(.1 * pool))
    cuts = [0, pool - 2 * reserve, pool - reserve, pool, n]
    names = ["train", "dev", "calibration", "test"]
    lookup = {g: name for name, a, b in zip(names, cuts, cuts[1:]) for g in groups[a:b]}
    result = {name: [] for name in names}
    for row in rows:
        result[lookup[root(row["id"])]].append({**row, "group": root(row["id"])})
    return result


def prompt(row):
    # Dataset candidates have placeholder proofs. Do not silently parse arbitrary Lean.
    candidate = re.sub(r"\s*:=\s*(?:by\s+)?sorry\s*$", "", row["lean4_prediction"].strip())
    if re.search(r":=\s*(?:by\b|sorry\b)", candidate):
        raise ValueError(f"Non-placeholder proof needs audited extraction: {row['id']}")
    return (f"<problem>\n{row['nl_statement']}\n</problem>\n"
            f"<lean_context>\n{row['lean4_src_header']}\n</lean_context>\n"
            f"<candidate>\n{candidate}\n</candidate>\nFaithfulness:")


def prepare(out):
    if (out / "manifest.json").exists():
        raise FileExistsError("Prepared data already exists; use a new output directory.")
    from datasets import load_dataset
    from huggingface_hub import HfApi
    from transformers import AutoTokenizer
    out.mkdir(parents=True, exist_ok=True)
    api = HfApi()
    data_rev = api.dataset_info(DATA).sha
    model_rev = api.model_info(MODEL).sha
    data = load_dataset(DATA, revision=data_rev)
    rows = [dict(row) for split in data.values() for row in split]
    tokenizer = AutoTokenizer.from_pretrained(MODEL, revision=model_rev)
    splits = partition(rows)
    audit = []
    for name, examples in splits.items():
        prepared = []
        for row in examples:
            try:
                text = prompt(row)
                ids = tokenizer(text, truncation=False)["input_ids"]
                if len(ids) > 4096:
                    raise ValueError("context_overflow")
                prepared.append({"id": row["id"], "group": row["group"],
                                 "text": text, "label": int(row["correct"]),
                                 "tokens": len(ids)})
            except ValueError as exc:
                audit.append({"id": row["id"], "split": name, "reason": str(exc)})
        write(out / f"{name}.json", prepared)
    write(out / "excluded.json", audit)
    manifest = {"model": MODEL, "model_revision": model_rev,
                "dataset": DATA, "dataset_revision": data_rev, "seed": 42,
                "split": "custom grouped 80/20; development/calibration inside 80%",
                "counts": {k: {"rows": len(v), "groups": len({r['group'] for r in v})}
                           for k, v in splits.items()},
                "prepared_counts": {k: len(load_rows(out, k)) for k in splits},
                "audit_required": "Review excluded rows, label quality and near-duplicates before training."}
    manifest["prepared_sha256"] = {k: hashlib.sha256((out / f"{k}.json").read_bytes()).hexdigest() for k in splits}
    write(out / "manifest.json", manifest)
    print(json.dumps(manifest, indent=2))


def load_rows(out, name):
    path = out / f"{name}.json"
    if (out / "manifest.json").exists():
        manifest = json.loads((out / "manifest.json").read_text())
        if hashlib.sha256(path.read_bytes()).hexdigest() != manifest["prepared_sha256"][name]:
            raise ValueError(f"Prepared split changed: {name}")
    return json.loads(path.read_text())


def train(out, deadline=None, local=False):
    import time
    import torch
    from datasets import Dataset
    from peft import LoraConfig, TaskType, get_peft_model
    from transformers import (AutoModelForSequenceClassification, AutoTokenizer,
                              DataCollatorWithPadding, Trainer, TrainingArguments, TrainerCallback, set_seed)
    set_seed(42)
    if (out / "adapter").exists():
        raise FileExistsError("Adapter already exists; use a new experiment directory.")
    if local and not torch.backends.mps.is_available():
        raise RuntimeError("Apple Metal GPU is unavailable.")
    if not local and not torch.cuda.is_available():
        raise RuntimeError("This minimal training implementation requires a CUDA GPU; use Modal.")
    manifest = json.loads((out / "manifest.json").read_text())
    model_name = manifest.get("training_model", MODEL)
    tokenizer = AutoTokenizer.from_pretrained(model_name, revision=manifest["model_revision"])
    tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"
    def dataset(name):
        rows = load_rows(out, name)
        counts = Counter(r["group"] for r in rows)
        items = []
        for row in rows:
            item = tokenizer(row["text"], truncation=False)
            item.update(labels=float(row["label"]), weight=len(rows) / (len(counts) * counts[row["group"]]))
            items.append(item)
        return Dataset.from_list(items)
    model = AutoModelForSequenceClassification.from_pretrained(
        model_name, revision=manifest["model_revision"], num_labels=1,
        torch_dtype=torch.float32 if local else torch.bfloat16, attn_implementation="sdpa")
    model.config.pad_token_id = tokenizer.pad_token_id
    model.config.use_cache = False
    model = get_peft_model(model, LoraConfig(
        task_type=TaskType.SEQ_CLS, r=16, lora_alpha=32, lora_dropout=.05,
        target_modules=["q_proj", "v_proj"], modules_to_save=["score"]))

    class BalancedTrainer(Trainer):
        def compute_loss(self, model, inputs, return_outputs=False, **kwargs):
            labels, weights = inputs.pop("labels"), inputs.pop("weight")
            outputs = model(**inputs)
            loss = torch.nn.functional.binary_cross_entropy_with_logits(
                outputs.logits.float().view(-1), labels.float().view(-1), reduction="none")
            loss = (loss * weights).mean()
            return (loss, outputs) if return_outputs else loss

    args = TrainingArguments(
        output_dir=str(out / "checkpoints"), num_train_epochs=1000,
        per_device_train_batch_size=2,
        gradient_accumulation_steps=8, lr_scheduler_type="constant",
        per_device_eval_batch_size=1, learning_rate=1e-4,
        bf16=not local, gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False},
        eval_strategy="steps", save_strategy="steps", eval_steps=20 if local else 50, save_steps=20 if local else 50,
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss", greater_is_better=False,
        save_total_limit=1, logging_steps=1, report_to="none",
        remove_unused_columns=False, label_names=["labels"], seed=42)
    parameters = [(n, p) for n, p in model.named_parameters() if p.requires_grad]
    optimizer = torch.optim.AdamW([
        {"params": [p for n, p in parameters if "score" not in n], "lr": 1e-4},
        {"params": [p for n, p in parameters if "score" in n], "lr": 1e-3},
    ])
    trainer = BalancedTrainer(model=model, args=args, train_dataset=dataset("train"),
                              eval_dataset=dataset("dev"),
                              data_collator=DataCollatorWithPadding(tokenizer), optimizers=(optimizer, None))
    trainer.model_accepts_loss_kwargs = False
    class StopRun(TrainerCallback):
        best = float("inf")
        stale = 0
        reason = None

        def on_log(self, args, state, control, **kwargs):
            write(out / "training_metrics.json", state.log_history)

        def on_step_end(self, args, state, control, **kwargs):
            if deadline is not None and time.time() >= deadline:
                self.reason = "time_budget"
                control.should_training_stop = True
                control.should_evaluate = True
                control.should_save = True
            return control

        def on_evaluate(self, args, state, control, metrics, **kwargs):
            loss = metrics["eval_loss"]
            if loss < self.best - .001:
                self.best, self.stale = loss, 0
            else:
                self.stale += 1
            if self.stale >= 3:
                self.reason = self.reason or "development_loss_plateau"
                control.should_training_stop = True
            write(out / "training_metrics.json", state.log_history)
            return control

    stopper = StopRun()
    trainer.add_callback(stopper)
    if not local:
        torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter()
    result = trainer.train()
    trainer.save_model(str(out / "adapter"))
    tokenizer.save_pretrained(out / "adapter")
    write(out / "training_metrics.json", trainer.state.log_history)
    summary = {"optimizer_steps": trainer.state.global_step,
               "stop_reason": stopper.reason or "epoch_limit",
               "best_dev_loss": trainer.state.best_metric,
               "training_seconds": time.perf_counter() - started,
               "gpu": "Apple Metal (MPS)" if local else torch.cuda.get_device_name(),
               "model": model_name,
               "peak_allocated_gib": None if local else torch.cuda.max_memory_allocated()/2**30,
               "trainable_parameters": sum(p.numel() for _, p in parameters),
               "test_set_used": False, "training_metrics": result.metrics}
    write(out / "training_summary.json", summary)
    print(json.dumps(summary, indent=2))


def evaluate(out, final_test=False):
    import numpy as np
    import torch
    from peft import PeftModel
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
    manifest = json.loads((out / "manifest.json").read_text())
    tokenizer = AutoTokenizer.from_pretrained(out / "adapter")
    model = AutoModelForSequenceClassification.from_pretrained(
        MODEL, revision=manifest["model_revision"], num_labels=1, torch_dtype=torch.bfloat16)
    model = PeftModel.from_pretrained(model, out / "adapter").cuda().eval()
    model.config.pad_token_id = tokenizer.pad_token_id
    def predict(rows):
        logits = []
        with torch.inference_mode():
            for row in rows:
                batch = tokenizer(row["text"], return_tensors="pt").to("cuda")
                logits.append(model(**batch).logits.float().item())
        return torch.tensor(logits), torch.tensor([r["label"] for r in rows], dtype=torch.float32)
    if not final_test:
        logits, labels = predict(load_rows(out, "calibration"))
        log_t = torch.zeros(1, requires_grad=True)
        optimizer = torch.optim.LBFGS([log_t], max_iter=50)
        def closure():
            optimizer.zero_grad()
            loss = torch.nn.functional.binary_cross_entropy_with_logits(logits / log_t.exp(), labels)
            loss.backward()
            return loss
        optimizer.step(closure)
        temp = log_t.exp().item()
        probs = torch.sigmoid(logits / temp).numpy()
        # Empirical operating point, not a certified error bound.
        choices = []
        for threshold in np.unique(probs):
            accepted = probs >= threshold
            if accepted.sum() >= 20 and (1 - labels.numpy()[accepted]).mean() <= .05:
                choices.append(float(threshold))
        write(out / "calibration_settings.json", {"temperature": temp,
              "accept_threshold": min(choices) if choices else None,
              "note": "Empirical <=5% error with >=20 accepts; no statistical guarantee."})
        return
    if (out / "test_metrics.json").exists():
        raise FileExistsError("Final test already evaluated; preserve its results.")
    calibration = json.loads((out / "calibration_settings.json").read_text())
    rows = load_rows(out, "test")
    logits, labels = predict(rows)
    probs = torch.sigmoid(logits / calibration["temperature"]).numpy()
    y = labels.numpy()
    threshold = calibration["accept_threshold"]
    accepted = probs >= threshold if threshold is not None else np.zeros(len(y), dtype=bool)
    metrics = {"rows": len(rows), "coverage": float(accepted.mean()),
               "accepted": int(accepted.sum()), "wrong_accepted": int(((y == 0) & accepted).sum()),
               "accepted_error": float((1-y[accepted]).mean()) if accepted.any() else None,
               "brier": float(((probs-y)**2).mean()), "threshold": threshold}
    write(out / "test_metrics.json", metrics)
    write(out / "test_predictions.json", [{"id": r["id"], "group": r["group"],
          "label": int(label), "p_faithful": float(p)} for r, label, p in zip(rows, y, probs)])
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    order = np.argsort(-probs)
    # Only realizable thresholds: include all tied predictions together.
    ends = np.r_[np.where(np.diff(probs[order]) != 0)[0], len(y)-1]
    plt.plot((ends+1)/len(y), np.cumsum(1-y[order])[ends]/(ends+1))
    plt.xlabel("Acceptance coverage")
    plt.ylabel("Error among accepted specifications")
    plt.title("Trained classifier — single run, no confidence intervals")
    for ext in ("png", "pdf"):
        plt.savefig(out / f"risk_coverage.{ext}", bbox_inches="tight")
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["prepare", "train", "calibrate", "test"])
    parser.add_argument("--out", type=Path, default=Path("artifacts"))
    parser.add_argument("--deadline", type=float)
    parser.add_argument("--local", action="store_true")
    args = parser.parse_args()
    {"prepare": prepare, "train": lambda out: train(out, args.deadline, args.local), "calibrate": evaluate,
     "test": lambda out: evaluate(out, final_test=True)}[args.action](args.out)
