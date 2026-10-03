"""Load ProofNetVerif rows used to benchmark statement formalization."""

import os

DATASET = "PAug/ProofNetVerif"
LEAN_TOOLCHAIN = "leanprover/lean4:v4.8.0"


def use_proofnet_toolchain() -> None:
    """Select ProofNetVerif's Lean version without changing the user's elan default."""
    os.environ["ELAN_TOOLCHAIN"] = LEAN_TOOLCHAIN


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
