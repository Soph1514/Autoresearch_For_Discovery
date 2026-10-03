"""Fetch formal problem statements from CAM-Bench."""

import json
from dataclasses import dataclass
from pathlib import Path
from urllib.request import urlopen

REVISION = "a36ff77720e2f5f149bed756d4dd5370ba1b43ef"
DATASET_URL = (
    "https://raw.githubusercontent.com/optpku/CAM-Bench/"
    f"{REVISION}/CAM-Bench.json"
)
DEFAULT_CACHE = Path(__file__).resolve().parents[3] / "runs" / "CAM-Bench.json"
DEFAULT_MAP = Path(__file__).resolve().parents[3] / "problems" / "benchmark_map.json"


@dataclass(frozen=True)
class CAMBenchProblem:
    id: int
    name: str
    informal_statement: str
    formal_statement: str


def pull_cam_bench(
    problem_name: str, cache: Path | None = None, mapping: Path | None = None
) -> CAMBenchProblem:
    """Return the CAM-Bench reference mapped to a local problem directory name."""
    mapping = (mapping or DEFAULT_MAP).resolve()
    benchmark_name = json.loads(mapping.read_text()).get(problem_name)
    if not benchmark_name:
        raise ValueError(f"No CAM-Bench mapping for problem: {problem_name}")

    cache = (cache or DEFAULT_CACHE).resolve()
    if not cache.is_file():
        cache.parent.mkdir(parents=True, exist_ok=True)
        with urlopen(DATASET_URL, timeout=60) as response:
            cache.write_bytes(response.read())

    entries = json.loads(cache.read_text())
    matches = [entry for entry in entries
               if f"{entry['book']} {entry['exercise']}".casefold() == benchmark_name.casefold()]
    if not matches:
        raise ValueError(f"Unknown CAM-Bench problem in mapping: {benchmark_name}")
    if len(matches) > 1:
        ids = ", ".join(str(entry["id"]) for entry in matches)
        raise ValueError(f"Ambiguous CAM-Bench mapping: {benchmark_name} (IDs: {ids})")
    entry = matches[0]
    return CAMBenchProblem(
        id=entry["id"],
        name=f"{entry['book']} {entry['exercise']}",
        informal_statement=entry["informal_statement"],
        formal_statement=entry["formal_statement"],
    )
