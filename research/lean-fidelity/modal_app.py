"""One bounded experiment; importing never launches training."""
import json
import time
from pathlib import Path
import modal

HERE = Path(__file__).parent
BUDGET_USD = 20
# Conservative $5/hour allowance vs ~$2.95/hour at published resource rates.
RATE_USD_HOUR = 5
MAX_SECONDS = min(3600, int((BUDGET_USD - 1) / RATE_USD_HOUR * 3600))
SEEDS = ("manifest", "train", "dev", "calibration", "test")
app = modal.App("lean-fidelity-research")
image = (modal.Image.debian_slim(python_version="3.11")
         .pip_install("torch==2.7.1", "transformers==4.56.2", "peft==0.17.1",
                      "accelerate==1.10.1", "datasets==4.1.1", "scikit-learn==1.7.2")
         .add_local_file(HERE / "experiment.py", "/root/experiment.py"))
for name in SEEDS:
    source = HERE / "artifacts" / f"{name}.json"
    if source.exists():
        image = image.add_local_file(source, f"/seed/{name}.json")
volume = modal.Volume.from_name("lean-fidelity-research", create_if_missing=True)


@app.function(image=image, gpu="A100-80GB", cpu=(2, 4), memory=(16384, 32768),
              timeout=MAX_SECONDS, retries=0, scaledown_window=2,
              volumes={"/artifacts": volume}, max_containers=1)
def run(run_id: str, deadline: float):
    import shutil
    import subprocess
    target = Path("/artifacts") / run_id
    # A restarted input cannot silently repeat a paid experiment.
    target.mkdir(exist_ok=False)
    for name in SEEDS:
        shutil.copyfile(f"/seed/{name}.json", target / f"{name}.json")
    status = {"run_id": run_id, "budget_usd": BUDGET_USD, "deadline": deadline,
              "rate_allowance_usd_hour": RATE_USD_HOUR, "status": "running"}
    try:
        for action in ("train", "calibrate", "test"):
            remaining = deadline - time.time() - 20
            if remaining < 60:
                status.update(status="time_limit", pending_action=action)
                break
            command = ["python", "/root/experiment.py", action, "--out", str(target)]
            if action == "train":
                command += ["--deadline", str(deadline - 300)]
            subprocess.run(command, check=True, timeout=remaining)
            volume.commit()
        else:
            status["status"] = "completed"
    except subprocess.TimeoutExpired:
        status["status"] = "time_limit"
    except Exception as exc:
        status.update(status="failed", error=str(exc))
        raise
    finally:
        (target / "run_status.json").write_text(json.dumps(status, indent=2))
        volume.commit()
    return {p.name: p.read_bytes() for p in target.iterdir()
            if p.is_file() and p.stem not in SEEDS}


@app.local_entrypoint()
def main(confirm_training: bool = False):
    if not confirm_training:
        raise ValueError("Pass --confirm-training to launch the bounded full experiment.")
    if not all((HERE / "artifacts" / f"{name}.json").exists() for name in SEEDS):
        raise FileNotFoundError("Prepare and review local data first.")
    run_id = "run-" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    deadline = time.time() + MAX_SECONDS
    call = run.spawn(run_id, deadline)
    try:
        result = call.get(timeout=max(1, deadline - time.time()))
    except BaseException:
        call.cancel(terminate_containers=True)
        raise
    target = HERE / "artifacts" / run_id
    target.mkdir()
    for name, content in result.items():
        (target / name).write_bytes(content)
    print(f"Downloaded reports to {target}; adapter remains in the Modal volume.")
