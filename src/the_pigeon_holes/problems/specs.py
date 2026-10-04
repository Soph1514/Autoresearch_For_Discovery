"""Read the shared natural-language statements under the repository's problems/.

Keeping one copy of each statement means the text a run is generated from is the
same text the formalizer receives.
"""

from __future__ import annotations

import json
from importlib.resources import files


def load_problem_text(name: str) -> str:
    """Return the natural-language statement for a built-in problem."""
    path = files("problems").joinpath(name.replace("-", "_"), "problem.txt")
    if not path.is_file():
        raise ValueError(f"Unknown problem statement: {name}")
    return path.read_text().strip()


def load_instances(name: str) -> list[dict]:
    """Load fixed example instances and reporting-only targets from problems/."""
    path = files("problems").joinpath(name.replace("-", "_"), "instances.json")
    return json.loads(path.read_text())
