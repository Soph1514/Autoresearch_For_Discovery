"""Generate and save ProofNetVerif predictions with Lea; safe to resume."""

import argparse
import json
import os
from pathlib import Path
from uuid import uuid4
from lean_interact.project import TempRequireProject
from lean_interact.utils import extract_last_theorem
from .formalise import DEFAULT_MODEL, ROOT, lea_root, load_dotenv, require_model_credentials
from .lea import formalize
from .proofnet import load_problems, use_proofnet_toolchain

TASK = """Translate the natural-language statement into exactly one Lean theorem statement.
Use the supplied source header and its namespace. Create Generated.lean containing that
header followed by the theorem. Preserve every assumption and the exact conclusion.
The theorem may end with `:= by sorry`: only its statement is evaluated. Check that the
file typechecks. Do not add definitions, axioms, extra assumptions, or extra theorems."""


def generate(split: str, limit: int | None) -> None:
    load_dotenv()
    model = os.environ.get("LEA_MODEL", DEFAULT_MODEL)
    require_model_credentials(model)
    rows = load_problems(split, limit)
    destination = ROOT / "runs" / "proofnetverif" / f"{split}.jsonl"
    destination.parent.mkdir(parents=True, exist_ok=True)
    done = ({json.loads(line)["id"] for line in destination.read_text().splitlines()}
            if destination.exists() else set())
    use_proofnet_toolchain()
    project = TempRequireProject(lean_version="v4.8.0", require="mathlib")
    for index, row in enumerate(rows, 1):
        if row["id"] in done:
            print(f"EXISTS       {row['id']}")
            continue
        print(f"FORMALISING  {index}/{len(rows)} {row['id']}")
        run = ROOT / "runs" / "proofnetverif" / f"{row['id']}-{uuid4().hex[:8]}"
        run.mkdir(parents=True)
        try:
            generated = formalize(
                lea_root=lea_root(), task=TASK,
                statement=row["lean4_src_header"] + "\n\nNatural-language statement:\n" + row["nl_statement"],
                lean_project=Path(project.get_directory()), output=run, model=model,
                max_turns=12, timeout=None, allow_sorry=True,
            )
            source = generated.read_text()
            record = {"id": row["id"],
                      "lean4_prediction": source[extract_last_theorem(source):].strip()}
            with destination.open("a") as file:
                file.write(json.dumps(record) + "\n")
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
