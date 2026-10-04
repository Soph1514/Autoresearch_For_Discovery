"""Run the evolution loop on the first autocorrelation inequality.

Usage:
    ANTHROPIC_API_KEY=... uv run python scripts/run_autocorrelation.py --seed 0

A thin wrapper over scripts/run_problem.py that adds the one comparison specific to
this problem: whether the rechecked exact C1 falls below the published upper bound.
The problem is open, so there is no optimum to match, only a bound to beat.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from problems.autocorrelation.fitness import PUBLISHED_UPPER_BOUND  # noqa: E402
from the_pigeon_holes.pipeline.runner import PROBLEMS, run_problem  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--n", type=int, default=600, help="fixed output length")
    parser.add_argument("--model", default=os.environ.get("RESEARCH_MODEL") or os.environ.get("LEVOLVE_MODEL"))
    parser.add_argument("--max-tokens", type=int, default=200_000)
    parser.add_argument("--max-minutes", type=float, default=30.0)
    parser.add_argument("--max-critic-calls", type=int, default=200)
    parser.add_argument("--memory-mb", type=int, default=256)
    return parser.parse_args()


def add_published_bound_comparison(summary: dict) -> dict:
    """Compare the rechecked exact C1 against the published upper bound."""
    rechecked = [
        case["metrics"]["c1"]
        for case in (summary.get("independent_recheck") or {}).values()
        if case.get("ok") and "c1" in (case.get("metrics") or {})
    ]
    if len(rechecked) == 1:
        exact = Fraction(rechecked[0])
        summary["best_exact_c1"] = str(exact)
        summary["beats_published_bound_exact"] = exact < PUBLISHED_UPPER_BOUND
        summary["published_upper_bound_float"] = float(PUBLISHED_UPPER_BOUND)
    return summary


async def main() -> int:
    args = parse_args()
    if not args.model:
        print("Set RESEARCH_MODEL or pass --model before the live run.", file=sys.stderr)
        return 2
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set; the live run needs it.", file=sys.stderr)
        return 2

    problem = PROBLEMS["autocorrelation"]
    run_id = f"autocorr-seed{args.seed}-{uuid.uuid4().hex[:8]}"
    run_dir = ROOT / "runs" / run_id
    summary = add_published_bound_comparison(await run_problem(
        problem,
        run_dir=run_dir,
        run_id=run_id,
        model=args.model,
        seed=args.seed,
        max_tokens=args.max_tokens,
        max_minutes=args.max_minutes,
        max_critic_calls=args.max_critic_calls,
        memory_mb=args.memory_mb,
        contract_kwargs={"n": args.n},
    ))
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str) + "\n")
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
