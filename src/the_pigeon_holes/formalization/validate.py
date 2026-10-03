"""Compile a problem's equivalence proof and reject untrusted axioms."""

import argparse
import re
import subprocess
from pathlib import Path

ALLOWED_AXIOMS = {"propext", "Classical.choice", "Quot.sound"}
THEOREM = "generated_iff_reference"


def check_axioms(output: str) -> bool:
    if f"'{THEOREM}' does not depend on any axioms" in output:
        return True
    match = re.search(rf"'{THEOREM}' depends on axioms: \[([^\]]*)\]", output)
    if not match:
        return False
    used = {name.strip() for name in match.group(1).split(",") if name.strip()}
    return used <= ALLOWED_AXIOMS


def validate(problem: Path, lean_root: Path, lake: str = "lake") -> tuple[bool, str]:
    validation = problem.resolve() / "Validation.lean"
    if not validation.is_file():
        return False, f"Missing {validation}"
    build = subprocess.run(
        [lake, "build", "Validation"], cwd=lean_root.resolve(),
        capture_output=True, text=True, check=False,
    )
    if build.returncode != 0:
        return False, build.stdout + build.stderr
    result = subprocess.run(
        [lake, "env", "lean", str(validation)],
        cwd=lean_root.resolve(), capture_output=True, text=True, check=False,
    )
    output = result.stdout + result.stderr
    if result.returncode != 0:
        return False, output
    if not check_axioms(output):
        return False, output + "\nUnapproved axiom or missing #print axioms.\n"
    return True, output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("problem", type=Path)
    parser.add_argument("--lean-root", type=Path, default=Path("problems/lean"))
    parser.add_argument("--lake", default="lake")
    args = parser.parse_args()
    valid, output = validate(args.problem, args.lean_root, args.lake)
    if output:
        print(output, end="" if output.endswith("\n") else "\n")
    print("VALID" if valid else "INVALID")
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
