"""Read the shared natural-language statements under the repository's problems/.

Keeping one copy of each statement means the text a run is generated from is the
same text the formalizer receives.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def load_problem_text(name: str) -> str:
    """Return the natural-language statement for a built-in problem."""
    path = ROOT / "problems" / name / "problem.txt"
    if not path.is_file():
        raise ValueError(f"Unknown problem statement: {name}")
    return path.read_text().strip()


def load_instances(name: str) -> list[dict]:
    """Load fixed example instances and reporting-only targets from problems/."""
    return json.loads((ROOT / "problems" / name / "instances.json").read_text())
