"""Load ProofNetVerif rows used to benchmark statement formalization."""

import os
import subprocess
import re
from pathlib import Path

DATASET = "PAug/ProofNetVerif"
LEAN_TOOLCHAIN = "leanprover/lean4:v4.8.0"


def problem_directory(root: Path, split: str, problem_id: str) -> Path:
    """Return the readable artifact directory for one dataset problem."""
    name = re.sub(r"[^A-Za-z0-9._-]+", "__", problem_id).strip("_")
    return root / "runs" / "proofnetverif" / split / name


def use_proofnet_toolchain() -> None:
    """Select ProofNetVerif's Lean version without changing the user's elan default."""
    os.environ["ELAN_TOOLCHAIN"] = LEAN_TOOLCHAIN


def proofnet_project():
    """Return a ready Lean 4.8 Mathlib project, repairing partial caches."""
    from lean_interact.project import TempRequireProject

    use_proofnet_toolchain()
    project = TempRequireProject(lean_version="v4.8.0", require="mathlib")
    root = Path(project.get_directory())
    mathlib_lib = root / ".lake/packages/mathlib/.lake/build/lib"
    mathlib_oleans = (mathlib_lib / "Mathlib.olean", mathlib_lib / "lean/Mathlib.olean")
    if not any(path.is_file() for path in mathlib_oleans):
        # On some macOS versions Mathlib's downloaded cache executable cannot
        # run. Invoking its Lean source directly is the supported equivalent.
        subprocess.run(
            ["lake", "env", "lean", "--run", ".lake/packages/mathlib/Cache/Main.lean", "get"],
            cwd=root, check=True,
        )
    if not any(path.is_file() for path in mathlib_oleans):
        raise RuntimeError("Mathlib cache setup completed without Mathlib.olean")
    return project


def load_problems(split: str = "valid", limit: int | None = None) -> list[dict]:
    """Load one row per theorem ID, preserving dataset order."""
    from datasets import load_dataset

    unique, seen = [], set()
    for row in load_dataset(DATASET, split=split):
        if row["id"] in seen:
            continue
        seen.add(row["id"])
        unique.append(dict(row))
        if limit is not None and len(unique) >= limit:
            break
    return unique
