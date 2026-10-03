"""Check generated Lean, and compare it with a reference when one exists."""

import argparse
import os
import re
import subprocess
from pathlib import Path

ALLOWED_AXIOMS = {"propext", "Classical.choice", "Quot.sound"}
THEOREM = "generated_iff_reference"


def check_axioms(output: str, theorem: str = THEOREM) -> bool:
    if f"'{theorem}' does not depend on any axioms" in output:
        return True
    match = re.search(rf"'{re.escape(theorem)}' depends on axioms: \[([^\]]*)\]", output)
    if not match:
        return False
    used = {name.strip() for name in match.group(1).split(",") if name.strip()}
    return used <= ALLOWED_AXIOMS


def contains_cheating(source: str) -> bool:
    source = re.sub(r"/-.*?-/", "", source, flags=re.DOTALL)
    source = re.sub(r"--.*", "", source)
    return bool(re.search(r"\b(sorry|admit)\b|^\s*axiom\b", source, re.MULTILINE))


def validate(problem: Path, lean_root: Path, lake: str = "lake") -> tuple[bool, str]:
    problem = problem.resolve()
    generated = problem / "Generated.lean"
    if not generated.is_file():
        return False, f"Missing {generated}"
    if contains_cheating(generated.read_text()):
        return False, "Generated.lean contains sorry, admit, or a custom axiom."

    reference = problem / "Reference.lean"
    environment = os.environ.copy()
    environment["LEAN_PATH"] = str(problem)
    if not reference.is_file():
        result = subprocess.run(
            [lake, "env", "lean", str(generated)], cwd=lean_root.resolve(),
            capture_output=True, text=True, check=False, env=environment,
        )
        return result.returncode == 0, result.stdout + result.stderr

    validation = problem / "Validation.lean"
    if not validation.is_file():
        return False, f"Missing {validation}"
    result = subprocess.run(
        [lake, "env", "lean", str(validation)],
        cwd=lean_root.resolve(), capture_output=True, text=True, check=False,
        env=environment,
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
