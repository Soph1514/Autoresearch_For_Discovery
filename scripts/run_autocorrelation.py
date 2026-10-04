"""Run the stage 0 evolution loop on the first autocorrelation inequality.

Usage:
    ANTHROPIC_API_KEY=... uv run python scripts/run_autocorrelation.py --seed 0

Every attempt, including rejected ones, is appended to runs/<run-id>/attempts.jsonl.
The final result is re-checked with the exact fitness function in runs/<run-id>/summary.json.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import uuid
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from the_pigeon_holes.evaluation.production import SandboxCandidateEvaluator  # noqa: E402
from the_pigeon_holes.evolution.loop import EvolutionLoop  # noqa: E402
from the_pigeon_holes.evolution.models import EvolutionConfig, EvolutionLimits  # noqa: E402
from the_pigeon_holes.execution.container_runner import ContainerLimits, run_candidate_async  # noqa: E402
from the_pigeon_holes.fitness.autocorrelation import (  # noqa: E402
    AutocorrelationFitnessFunction,
    FITNESS_FUNCTION_VERSION,
    PUBLISHED_UPPER_BOUND,
    c1,
)
from the_pigeon_holes.problems.autocorrelation import autocorrelation_contract  # noqa: E402
from the_pigeon_holes.llm.budget import ProviderTokenBudget  # noqa: E402
from the_pigeon_holes.llm.critic import AnthropicCritic, CriticConfig  # noqa: E402
from the_pigeon_holes.llm.program_generator import (  # noqa: E402
    AnthropicGeneratorConfig,
    AnthropicProgramGenerator,
)


class JsonlObserver:
    """Writes every lifecycle event to an append-only log. Returns quickly."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _write(self, record: dict) -> None:
        record["time"] = time.time()
        with self.path.open("a") as handle:
            handle.write(json.dumps(record, default=str) + "\n")

    def candidate_created(self, candidate) -> None:
        self._write({
            "event": "candidate_created", "id": candidate.id, "island": candidate.island_id,
            "operator": candidate.operator.value, "parents": list(candidate.parent_ids),
            "hypothesis": candidate.hypothesis, "source": candidate.source_code,
        })

    def evaluation_started(self, candidate) -> None:
        self._write({"event": "evaluation_started", "id": candidate.id})

    def evaluation_completed(self, evaluation) -> None:
        self._write({
            "event": "evaluation_completed", "id": evaluation.candidate_id,
            "valid": evaluation.valid, "metrics": dict(evaluation.metrics),
            "failure_stage": evaluation.failure_stage, "reasons": list(evaluation.failure_reasons),
            "cell": evaluation.behavioral_descriptor,
        })

    def generation_failed(self, failure) -> None:
        self._write({"event": "generation_failed", "request": failure.request_id, "error": failure.error})

    def assessment_recorded(self, assessment) -> None:
        self._write({"event": "assessment_recorded", **asdict(assessment), "risk_flags": list(assessment.risk_flags)})

    def state_committed(self, state) -> None:
        self._write({
            "event": "state_committed", "generation": state.generation,
            "islands": {i: sorted(island.cells) for i, island in state.active_islands.items()},
            "global_best": state.global_best_id,
        })


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--n", type=int, default=600, help="fixed output length")
    parser.add_argument("--model", default=os.environ.get("RESEARCH_MODEL") or os.environ.get("LEVOLVE_MODEL"))
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

    run_id = f"autocorr-seed{args.seed}-{uuid.uuid4().hex[:8]}"
    run_dir = ROOT / "runs" / run_id
    contract = autocorrelation_contract(args.n, memory_mb=args.memory_mb)
    limits = ContainerLimits(memory_mb=args.memory_mb, timeout_seconds=contract.resource_limits.case_time_seconds)
    evaluator = SandboxCandidateEvaluator(
        AutocorrelationFitnessFunction(), limits, max_workers=4
    )
    provider_budget = ProviderTokenBudget(args.max_tokens)
    generator = AnthropicProgramGenerator(AnthropicGeneratorConfig(model=args.model, max_concurrency=4, max_attempts=1), budget=provider_budget)
    critic = AnthropicCritic(CriticConfig(model=args.model), budget=provider_budget)
    config = EvolutionConfig(
        min_islands=2, max_islands=4, max_batch_size=8,
        pool_size=4, tournament_size=2, random_seed=args.seed,
        max_tokens_per_request=8_192,
    )
    observer = JsonlObserver(run_dir / "attempts.jsonl")
    loop = EvolutionLoop(
        config=config,
        limits=EvolutionLimits(
            max_tokens=args.max_tokens,
            max_time_seconds=args.max_minutes * 60,
            max_critic_calls=args.max_critic_calls,
        ),
        generator=generator,
        evaluator=evaluator,
        observer=observer,
        critic=critic,
        require_valid_seed=True,
    )
    try:
        outcome = await loop.run(contract)
    finally:
        await generator.aclose()
        await critic.aclose()

    best = outcome.best_candidate
    summary = {
        "run_id": run_id,
        "seed": args.seed,
        "fitness_function_version": FITNESS_FUNCTION_VERSION,
        "generator_model": args.model,
        "critic_model": args.model,
        "critic_prompt_version": "critic-v1",
        "lean_checked": False,
        "worker_image": evaluator.image,
        "stop_reason": outcome.stop_reason.value,
        "generations": outcome.generations_completed,
        "tokens_used": outcome.tokens_used,
        "best_stage0_c1": (outcome.best_evaluation.metrics.get("c1") if outcome.best_evaluation else None),
        "best_candidate": best.id if best else None,
    }
    if best is not None:
        # Re-run the best candidate and recompute C1 exactly, outside the loop.
        result = await run_candidate_async(best.source_code, "solve", {"n": args.n}, limits)
        if result.ok and isinstance(result.output, list) and len(result.output) == args.n:
            exact = c1(result.output)
            summary["best_exact_c1"] = str(exact)
            summary["beats_published_bound_exact"] = exact < PUBLISHED_UPPER_BOUND
            summary["published_upper_bound_float"] = float(PUBLISHED_UPPER_BOUND)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str) + "\n")
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
