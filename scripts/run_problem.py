"""Run the evolution loop on a built-in problem.

Usage:
    ANTHROPIC_API_KEY=... PYTHONPATH=src .venv/bin/python scripts/run_problem.py \
        --problem bin-packing --max-minutes 5

Every attempt, including rejected ones, is appended to runs/<run-id>/attempts.jsonl.
The winner is re-run in a fresh container and rescored with the registered fitness
function in runs/<run-id>/summary.json, next to each case's known target where one
exists.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from the_pigeon_holes.pipeline.runner import PROBLEMS, run_problem  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--problem", required=True, choices=sorted(PROBLEMS))
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--model", default=os.environ.get("RESEARCH_MODEL"))
    parser.add_argument("--max-tokens", type=int, default=200_000)
    parser.add_argument("--max-minutes", type=float, default=30.0)
    parser.add_argument("--max-critic-calls", type=int, default=200)
    parser.add_argument("--memory-mb", type=int, default=256)
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    if not args.model:
        print("Set RESEARCH_MODEL or pass --model before the live run.", file=sys.stderr)
        return 2
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set; the live run needs it.", file=sys.stderr)
        return 2

    problem = PROBLEMS[args.problem]
    run_id = f"{problem.name}-seed{args.seed}-{uuid.uuid4().hex[:8]}"
    summary = await run_problem(
        problem,
        run_dir=ROOT / "runs" / run_id,
        run_id=run_id,
        model=args.model,
        seed=args.seed,
        max_tokens=args.max_tokens,
        max_minutes=args.max_minutes,
        max_critic_calls=args.max_critic_calls,
        memory_mb=args.memory_mb,
    )
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
