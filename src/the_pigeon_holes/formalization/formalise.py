"""Public API for generating a problem formalisation with Lea."""

import os
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

from .lea import formalize

ROOT = Path(__file__).resolve().parents[3]
LEA_REPOSITORY = "https://github.com/darturi/lea-prover.git"
LEA_REVISION = "2709009dca410c1fc4d8de55f4e272f715b18334"
DEFAULT_MODEL = "anthropic/claude-sonnet-5-5"

"""
Formalise a general problem and return its Lean path and NL instance.
"""


def load_dotenv() -> None:
    """Load simple KEY=VALUE entries from the repository's ignored .env file."""
    dotenv = ROOT / ".env"
    if not dotenv.is_file():
        return
    for line in dotenv.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key, value)


def lea_root() -> Path:
    """Return the configured Lea checkout, cloning the pinned version if needed."""
    configured = os.environ.get("LEA_ROOT")
    if configured:
        return Path(configured)

    checkout = ROOT / ".cache" / "lea-prover"
    if not (checkout / "lea/cli.py").is_file():
        if checkout.exists():
            raise RuntimeError(f"Invalid Lea checkout: {checkout}")
        try:
            subprocess.run(["git", "clone", LEA_REPOSITORY, str(checkout)], check=True)
            subprocess.run(
                ["git", "-C", str(checkout), "checkout", LEA_REVISION], check=True
            )
        except Exception:
            shutil.rmtree(checkout, ignore_errors=True)
            raise
    return checkout


def require_model_credentials(model: str) -> None:
    if model.startswith("gemini/") and not (
        os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    ):
        raise RuntimeError(
            "Set GEMINI_API_KEY or GOOGLE_API_KEY for the selected Lea model."
        )
    if model.startswith("anthropic/") and not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("Set ANTHROPIC_API_KEY for the selected Lea model.")


def formalise(problem_name: str) -> tuple[str, str]:
    """Formalise a general problem and return its Lean path and NL instance."""
    load_dotenv()
    problem = ROOT / "problems" / problem_name
    general_problem = problem / "problem.txt"
    instance = problem / "instance.txt"
    if not general_problem.is_file() or not instance.is_file():
        raise ValueError(f"Unknown problem: {problem_name}")

    checkout = lea_root()
    model = os.environ.get("LEA_MODEL", DEFAULT_MODEL)
    require_model_credentials(model)
    output = ROOT / "runs" / f"{problem_name}-{uuid4().hex[:8]}"
    output.mkdir(parents=True)

    generated = formalize(
        lea_root=checkout,
        task=(ROOT / "problems" / "lea_task.txt").read_text(),
        statement=general_problem.read_text(),
        lean_project=ROOT / "problems" / "lean",
        output=output,
        model=model,
        max_turns=12,
        timeout=600,
    )
    destination = problem / "Generated.lean"
    shutil.copy2(generated, destination)
    return (str(generated), instance.read_text())
