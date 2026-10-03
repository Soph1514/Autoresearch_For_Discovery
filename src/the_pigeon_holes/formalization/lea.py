"""Invoke Lea's CLI in a per-run Lake workspace; validate its output separately."""

import json
import os
import shutil
import signal
import subprocess
from pathlib import Path


def formalize(*, lea_root: Path, task: str, statement: str, lean_project: Path,
              output: Path, model: str, max_turns: int, timeout: int, lake: str = "lake") -> Path:
    lea_root, output = lea_root.resolve(), output.resolve()
    if not (lea_root / "lea/cli.py").is_file():
        raise ValueError("--lea-root must point to a lea-prover source checkout")
    packages = (lean_project / ".lake/packages").resolve()
    if not packages.is_dir():
        raise RuntimeError("Set up the problem's Lean dependencies before running Lea")
    revision = subprocess.run(
        ["git", "-C", str(lea_root), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True, timeout=10,
    ).stdout.strip()
    workspace = output / "lea_workspace"
    workspace.mkdir()
    shutil.copy2(lean_project / "lean-toolchain", workspace)
    manifest = json.loads((lean_project / "lake-manifest.json").read_text())
    mathlib = next(package for package in manifest["packages"] if package["name"] == "mathlib")
    manifest["name"] = "lea_formalization"
    (workspace / "lake-manifest.json").write_text(json.dumps(manifest, indent=2))
    (workspace / "lakefile.toml").write_text(
        'name = "lea_formalization"\n\n[[require]]\nname = "mathlib"\n'
        f'git = {json.dumps(mathlib["url"])}\nrev = {json.dumps(mathlib["rev"])}\n'
    )
    (workspace / ".lake").mkdir()
    (workspace / ".lake/packages").symlink_to(packages, target_is_directory=True)
    instructions = (
        f"This run's Lean workspace is {workspace}. Use it instead of the default "
        "Lea workspace. Write only inside this directory. Do not alter toolchains, "
        "Lake configuration, dependencies, or reference/evaluation files. "
        "Use absolute paths for tools. Do not use sorry, admit or custom axioms.\n"
    )
    (workspace / "lea.md").write_text(instructions)
    generated = workspace / "Generated.lean"
    request = instructions + "\n" + task + "\n\nGeneral problem statement:\n" + statement
    (output / "lea_task.txt").write_text(request)
    # JSON is valid YAML; avoid an additional YAML dependency in this adapter.
    config = output / "lea_config.json"
    config.write_text(json.dumps({"agent": {
        "max_turns": max_turns,
        "tools": ["read_file", "write_file", "edit_file", "lean_check", "search_mathlib"],
        "permission_tier": "none",
    }}, indent=2))
    command = ["uv", "run", "--project", str(lea_root), "lea", "--config", str(config),
               "--model", model, "--max-turns", str(max_turns)]
    lake_path = shutil.which(lake)
    if lake_path is None:
        raise RuntimeError("Lake is unavailable; install elan or supply --lake")
    environment = os.environ.copy()
    environment["PATH"] = str(Path(lake_path).parent) + os.pathsep + environment.get("PATH", "")
    metadata = {"revision": revision, "model": model, "command": command,
                "max_turns": max_turns, "timeout_seconds": timeout}
    (output / "lea_run.json").write_text(json.dumps(metadata, indent=2))
    with (output / "lea.log").open("w") as log:
        process = subprocess.Popen(command, cwd=workspace, stdin=subprocess.PIPE,
                                   stdout=log, stderr=subprocess.STDOUT,
                                   text=True, start_new_session=True, env=environment)
        try:
            process.communicate(request, timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            raise RuntimeError("Lea timed out; see lea.log") from None
    if process.returncode != 0:
        raise RuntimeError(f"Lea exited with status {process.returncode}; see lea.log")
    if not generated.is_file():
        raise RuntimeError("Lea did not produce Generated.lean; see lea.log")
    return generated
