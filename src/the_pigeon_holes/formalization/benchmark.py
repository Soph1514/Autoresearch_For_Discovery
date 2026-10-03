"""Check the generated Lean equivalence proofs for ProofNetVerif problems."""

import argparse
import os
import re
import subprocess
from pathlib import Path

from .proofnet import load_problems, problem_directory, proofnet_project
from .validate import check_axioms, contains_cheating

ROOT = Path(__file__).resolve().parents[3]


NOT_EQUIVALENT = "generated_not_iff_reference"


def _check(problem: Path, project: Path) -> tuple[str, str]:
    required = [problem / name for name in
                ("Spec.txt", "Generated.lean", "Reference.lean", "Validation.lean")]
    missing = [path.name for path in required if not path.is_file()]
    if missing:
        return "not_proven", "missing " + ", ".join(missing)
    validation = problem / "Validation.lean"
    source = validation.read_text()
    if contains_cheating(source) or re.search(r"^\s*import\s+(Generated|Reference)\b", source, re.MULTILINE):
        return "not_proven", "Validation.lean uses sorry, a custom axiom, or an original theorem proof"
    environment = os.environ.copy()
    environment["LEAN_PATH"] = str(problem)
    result = subprocess.run(
        ["lake", "env", "lean", str(validation)], cwd=project,
        capture_output=True, text=True, check=False, env=environment,
    )
    output = result.stdout + result.stderr
    if result.returncode != 0:
        return "not_proven", output.strip().splitlines()[-1] if output.strip() else "Lean rejected Validation.lean"
    if check_axioms(output):
        return "equivalent", ""
    if check_axioms(output, NOT_EQUIVALENT):
        return "not_equivalent", ""
    return "not_proven", "unapproved axiom or missing #print axioms"


def run_benchmark(split: str = "valid") -> tuple[int, int, int]:
    project = Path(proofnet_project().get_directory())
    equivalent = not_equivalent = not_proven = 0
    for row in load_problems(split):
        problem = problem_directory(ROOT, split, row["id"])
        if not problem.exists():
            continue
        status, reason = _check(problem, project)
        if status == "equivalent":
            equivalent += 1
            print(f"PROVEN EQUIVALENT {row['id']}")
        elif status == "not_equivalent":
            not_equivalent += 1
            print(f"PROVEN NOT EQUIVALENT {row['id']}")
        else:
            not_proven += 1
            print(f"NOT PROVEN       {row['id']}: {reason}")
    print(f"\nProven semantically equivalent: {equivalent}")
    print(f"Proven not equivalent: {not_equivalent}")
    print(f"Not proven: {not_proven}")
    return equivalent, not_equivalent, not_proven


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=("valid", "test"), default="valid")
    args = parser.parse_args()
    run_benchmark(args.split)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
