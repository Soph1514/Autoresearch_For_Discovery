"""Incremental CSV metrics for the ProofNetVerif pipeline."""

import csv
import json
from pathlib import Path

FIELDS = [
    "problem_id",
    "generation_success", "generation_seconds", "generation_input_tokens",
    "generation_output_tokens", "generation_total_tokens", "generation_cost_usd", "generation_error",
    "verification_generation_success", "verification_generation_seconds",
    "verification_generation_input_tokens", "verification_generation_output_tokens",
    "verification_generation_total_tokens", "verification_generation_cost_usd",
    "verification_generation_error",
    "lean_verification_success", "lean_verification_seconds", "lean_verification_error",
    "result", "total_seconds", "total_tokens", "total_cost_usd",
]


def read_metrics(path: Path) -> dict[str, dict[str, str]]:
    if not path.is_file():
        return {}
    with path.open(newline="") as file:
        return {row["problem_id"]: row for row in csv.DictReader(file)}


def update_metrics(path: Path, problem_id: str, **values) -> None:
    rows = read_metrics(path)
    row = rows.get(problem_id, {field: "" for field in FIELDS})
    row["problem_id"] = problem_id
    row.update({key: str(value) for key, value in values.items()})
    seconds = sum(float(row.get(key) or 0) for key in
                  ("generation_seconds", "verification_generation_seconds", "lean_verification_seconds"))
    tokens = sum(int(float(row.get(key) or 0)) for key in
                 ("generation_total_tokens", "verification_generation_total_tokens"))
    cost = sum(float(row.get(key) or 0) for key in
               ("generation_cost_usd", "verification_generation_cost_usd"))
    row.update(total_seconds=f"{seconds:.3f}", total_tokens=str(tokens), total_cost_usd=f"{cost:.6f}")
    rows[problem_id] = row
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows.values())


def lea_metrics(run: Path, prefix: str, success: bool, error: str = "") -> dict:
    metadata = json.loads((run / "lea_run.json").read_text())
    return {
        f"{prefix}_success": success,
        f"{prefix}_seconds": metadata.get("elapsed_seconds", ""),
        f"{prefix}_input_tokens": metadata.get("input_tokens", ""),
        f"{prefix}_output_tokens": metadata.get("output_tokens", ""),
        f"{prefix}_total_tokens": metadata.get("total_tokens", ""),
        f"{prefix}_cost_usd": metadata.get("cost_usd", ""),
        f"{prefix}_error": error,
    }
