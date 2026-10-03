"""Fetch ProofNet specs/references and formalize the specs with Lea."""

import argparse
import os
import shutil
from pathlib import Path
from uuid import uuid4

from .formalise import DEFAULT_MODEL, ROOT, lea_root, load_dotenv, require_model_credentials
from .lea import formalize
from .proofnet import load_problems, problem_directory, proofnet_project

TASK = """Translate the natural-language statement into exactly one Lean theorem.
Create Generated.lean containing the supplied source header and that theorem. Preserve
every assumption and the exact conclusion. The theorem may end in `:= by sorry` because
the benchmark evaluates its statement. Do not add definitions, axioms, assumptions, or
other theorems. Check that Generated.lean compiles."""


def generate(split: str = "valid", limit: int | None = 10) -> None:
    load_dotenv()
    model = os.environ.get("LEA_MODEL", DEFAULT_MODEL)
    require_model_credentials(model)
    project = proofnet_project()  # preflight before spending model credits
    rows = load_problems(split, limit)

    for index, row in enumerate(rows, 1):
        problem = problem_directory(ROOT, split, row["id"])
        problem.mkdir(parents=True, exist_ok=True)
        (problem / "Spec.txt").write_text(row["nl_statement"])
        reference = row["lean4_src_header"] + "\n\n" + row["lean4_formalization"] + "\n"
        (problem / "Reference.lean").write_text(reference)
        generated = problem / "Generated.lean"
        if generated.is_file():
            print(f"EXISTS       {row['id']}")
            continue
        print(f"FORMALISING  {index}/{len(rows)} {row['id']}")
        run = ROOT / "runs" / "proofnetverif" / ".lea" / f"{row['id']}-{uuid4().hex[:8]}"
        run.mkdir(parents=True)
        try:
            result = formalize(
                lea_root=lea_root(), task=TASK,
                statement=row["lean4_src_header"] + "\n\nNatural-language statement:\n" + row["nl_statement"],
                lean_project=Path(project.get_directory()), output=run, model=model,
                max_turns=12, timeout=None, allow_sorry=True,
            )
            shutil.copy2(result, generated)
        except Exception as error:
            print(f"FAILED       {row['id']}: {error}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=("valid", "test"), default="valid")
    parser.add_argument("--limit", type=int, default=10,
                        help="unique problems (default: 10; use 0 for all)")
    args = parser.parse_args()
    generate(args.split, None if args.limit == 0 else args.limit)


if __name__ == "__main__":
    main()
