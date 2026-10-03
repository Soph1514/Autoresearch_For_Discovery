"""Evaluate saved formalizer outputs against ProofNetVerif with BEq+."""

import argparse
import json
from pathlib import Path
from lean_interact import AutoLeanServer, LeanREPLConfig
from lean_interact.project import TempRequireProject
from .beq_plus import beq_plus
from .proofnet import load_problems, use_proofnet_toolchain

ROOT = Path(__file__).resolve().parents[3]


def run_benchmark(split: str = "valid", timeout: int = 60) -> tuple[int, int]:
    output = ROOT / "runs" / "proofnetverif" / f"{split}.jsonl"
    if not output.is_file():
        raise RuntimeError(f"No predictions at {output}; run generate_benchmark first")
    predictions = {row["id"]: row for line in output.read_text().splitlines()
                   if (row := json.loads(line))}
    references = {row["id"]: row for row in load_problems(split)}
    use_proofnet_toolchain()
    project = TempRequireProject(lean_version="v4.8.0", require="mathlib")
    server = AutoLeanServer(config=LeanREPLConfig(project=project, verbose=False))
    equivalent = 0
    for problem_id, prediction in predictions.items():
        reference = references[problem_id]
        proved = beq_plus(reference["lean4_formalization"], prediction["lean4_prediction"],
                          reference["lean4_src_header"], server, timeout)
        equivalent += proved
        print(f"{'EQUIVALENT     ' if proved else 'NOT ESTABLISHED '} {problem_id}")
    total = len(predictions)
    print(f"\nBEq+ equivalent: {equivalent}/{total}")
    print(f"Equivalence not established: {total - equivalent}/{total}")
    return equivalent, total - equivalent


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=("valid", "test"), default="valid")
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()
    try:
        run_benchmark(args.split, args.timeout)
    except RuntimeError as error:
        print(f"BENCHMARK ERROR: {error}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
