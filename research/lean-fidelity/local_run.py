"""Download a smaller backbone, then run at most one hour on Apple Metal."""
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from huggingface_hub import HfApi, snapshot_download

HERE = Path(__file__).resolve().parent
MODEL = "Qwen/Qwen3-0.6B"

def main():
    revision = HfApi().model_info(MODEL).sha
    snapshot_download(MODEL, revision=revision,
                      allow_patterns=["*.json", "*.safetensors", "*.txt", "*.jinja"])
    out = HERE / "artifacts" / time.strftime("local-%Y%m%dT%H%M%S")
    out.mkdir()
    for name in ("manifest", "train", "dev"):
        shutil.copyfile(HERE / "artifacts" / f"{name}.json", out / f"{name}.json")
    manifest = json.loads((out / "manifest.json").read_text())
    manifest.update(training_model=MODEL, model_revision=revision, device="mps")
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    started = time.time()
    status = {"model": MODEL, "run_dir": str(out), "started": started,
              "max_seconds": 3600, "test_set_used": False}
    print(json.dumps(status), flush=True)
    try:
        subprocess.run([sys.executable, str(HERE / "experiment.py"), "train",
                        "--out", str(out), "--local", "--deadline", str(started + 3300)],
                       timeout=3600, check=True)
        status["status"] = "completed"
    except subprocess.TimeoutExpired:
        status["status"] = "hard_time_limit"
    except subprocess.CalledProcessError as exc:
        status.update(status="failed", exit_code=exc.returncode)
        raise
    finally:
        status["elapsed_seconds"] = time.time() - started
        (out / "run_status.json").write_text(json.dumps(status, indent=2))
        print(json.dumps(status), flush=True)

if __name__ == "__main__":
    main()
