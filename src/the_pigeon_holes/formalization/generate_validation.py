"""Generate one Lean semantic-equivalence proof for each benchmark problem."""

import argparse
import os
import shutil
from pathlib import Path
from uuid import uuid4

from .formalise import DEFAULT_MODEL, ROOT, lea_root, load_dotenv, require_model_credentials
from .lea import formalize
from .proofnet import load_problems, problem_directory, proofnet_project

TASK = """Create Validation.lean proving that the theorem statement in Generated.lean
is semantically equivalent to the theorem statement in Reference.lean.

Validation.lean must be self-contained apart from the source header/imports. Do not
import Generated or Reference, because their theorem proofs are `sorry`. Copy each
theorem's complete proposition exactly into definitions named `generated_statement`
and `reference_statement`, then prove:

theorem generated_iff_reference : generated_statement ↔ reference_statement := by ...

Both directions must be proved. Do not use `sorry`, `admit`, `axiom`, `unsafe`, or the
original theorem constants. End the file with `#print axioms generated_iff_reference`.
Compile and repair Validation.lean before finishing."""


def generate_validations(split: str = "valid", limit: int | None = 10) -> None:
    load_dotenv()
    model = os.environ.get("LEA_MODEL", DEFAULT_MODEL)
    require_model_credentials(model)
    project = proofnet_project()
    for row in load_problems(split, limit):
        problem = problem_directory(ROOT, split, row["id"])
        generated = problem / "Generated.lean"
        reference = problem / "Reference.lean"
        validation = problem / "Validation.lean"
        if validation.is_file():
            print(f"EXISTS       {row['id']}")
            continue
        if not generated.is_file() or not reference.is_file():
            print(f"MISSING      {row['id']}: generate benchmark files first")
            continue
        print(f"PROVING      {row['id']}")
        run = ROOT / "runs" / "proofnetverif" / ".lea" / f"validation-{row['id']}-{uuid4().hex[:8]}"
        run.mkdir(parents=True)
        try:
            result = formalize(
                lea_root=lea_root(), task=TASK, statement=f"ProofNetVerif problem {row['id']}",
                lean_project=Path(project.get_directory()), output=run, model=model,
                max_turns=16, timeout=None, output_name="Validation.lean",
                inputs={"Generated.lean": generated.read_text(),
                        "Reference.lean": reference.read_text()},
            )
            shutil.copy2(result, validation)
        except Exception as error:
            print(f"FAILED       {row['id']}: {error}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=("valid", "test"), default="valid")
    parser.add_argument("--limit", type=int, default=10,
                        help="unique problems (default: 10; use 0 for all)")
    args = parser.parse_args()
    generate_validations(args.split, None if args.limit == 0 else args.limit)


if __name__ == "__main__":
    main()
