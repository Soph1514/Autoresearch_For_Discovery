"""Public API for generating a problem formalisation with Lea."""

import os
import shutil
from pathlib import Path
from uuid import uuid4

from .lea import formalize

ROOT = Path(__file__).resolve().parents[3]


def formalise(problem_name: str) -> Path:
    """Formalise a named problem and return its Generated.lean path."""
    problem = ROOT / "problems" / problem_name
    statement = problem / "statement.txt"
    if not statement.is_file():
        raise ValueError(f"Unknown problem: {problem_name}")

    lea_root = Path(os.environ.get("LEA_ROOT", ROOT.parent / "lea-prover"))
    model = os.environ.get("LEA_MODEL", "gemini/gemini-3.1-pro-preview")
    output = ROOT / "runs" / f"{problem_name}-{uuid4().hex[:8]}"
    output.mkdir(parents=True)

    generated = formalize(
        lea_root=lea_root,
        task=(ROOT / "problems" / "lea_task.txt").read_text(),
        statement=statement.read_text(),
        lean_project=ROOT / "problems" / "lean",
        output=output,
        model=model,
        max_turns=12,
        timeout=600,
    )
    destination = problem / "Generated.lean"
    shutil.copy2(generated, destination)
    return destination
