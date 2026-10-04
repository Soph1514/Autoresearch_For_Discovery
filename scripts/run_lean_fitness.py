"""Compile a missing scorer, check candidates, optionally run the evolution loop.

Default: replay the saved, unedited Lea subset-sum formalization (no API charge).
--live: generate from problem.txt using the existing Lea CLI first.
--search-model: additionally evolve Python solvers using the existing Docker runner.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from the_pigeon_holes.fitness.compiler import lea_formalizer
from the_pigeon_holes.pipeline.runner import prepare_autoresearch, run_prepared


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--problem-dir", type=Path, default=ROOT / "problems/subset_sum")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--lea-model", default=os.environ.get("LEA_MODEL"))
    parser.add_argument("--candidate", action="append", help="Candidate JSON; may be repeated")
    parser.add_argument("--search-model", help="Run evolution after preparation (requires Docker/API key)")
    parser.add_argument("--max-minutes", type=float, default=2.0)
    args = parser.parse_args()
    if args.lea_model:
        os.environ["LEA_MODEL"] = args.lea_model
    problem = args.problem_dir
    run = ROOT / "runs" / ("lean-fitness-" + uuid4().hex[:8])

    def replay(statement: str, output: Path) -> Path:
        source = output / "Generated.lean"
        source.write_text((problem / "Generated.lean").read_text())
        details = json.loads((problem / "generation.json").read_text())
        details["replayed"] = True
        (output / "lea_run.json").write_text(json.dumps(details, indent=2))
        return source

    prepared = prepare_autoresearch(problem_name=problem.name,
        statement=(problem / "problem.txt").read_text(),
        instance=json.loads((problem / "instance.json").read_text()),
        lean_project=ROOT / "problems/lean", artifacts=run / "fitness",
        formalizer=lea_formalizer if args.live else replay)
    case = prepared.contract.evaluation_suite.cases[0]
    candidates = [json.loads(value) for value in args.candidate] if args.candidate else [[1, 1, 0], [0, 1, 1], [1, 0]]
    report = {"problem": problem.name, "fallback": prepared.used_lean_fallback,
              "mode": "live" if args.live else "replay",
              "direction": prepared.contract.optimisation_goal.primary.direction,
              "english_fidelity": "not_proven", "fitness": asdict(prepared.fitness.reference),
              "artifact": str(getattr(prepared.fitness, "artifact", "trusted")),
              "candidates": [{"candidate": c, **asdict(prepared.fitness.evaluate_case(case, c))} for c in candidates]}
    (run / "demo.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    if args.search_model:
        summary = asyncio.run(run_prepared(prepared, run_dir=run, model=args.search_model,
                                           max_minutes=args.max_minutes))
        print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
