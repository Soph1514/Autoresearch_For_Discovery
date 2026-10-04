"""Run the evolution loop on a built-in problem and recheck the winner.

The orchestration here is problem-agnostic. Everything specific to a problem comes
from its `ProblemContract` and its registered fitness function, so adding a
problem means registering a contract factory rather than writing a runner.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from fractions import Fraction
from pathlib import Path
from typing import Callable, Mapping

from the_pigeon_holes.evaluation.production import create_evaluator
from the_pigeon_holes.evolution.loop import EvolutionLoop
from the_pigeon_holes.evolution.models import EvolutionConfig, EvolutionLimits
from the_pigeon_holes.execution.container_runner import ContainerLimits, run_candidate_async
from the_pigeon_holes.fitness.base import FitnessFunction
from the_pigeon_holes.llm.budget import ProviderTokenBudget
from the_pigeon_holes.llm.critic import AnthropicCritic, CriticConfig
from the_pigeon_holes.llm.program_generator import (
    AnthropicGeneratorConfig,
    AnthropicProgramGenerator,
)
from the_pigeon_holes.models.problem_contract import ProblemContract
from the_pigeon_holes.problems import autocorrelation_contract, bin_packing_contract
from the_pigeon_holes.problems.bin_packing import BEST_KNOWN as BIN_PACKING_BEST_KNOWN

ENTRY_POINT = "solve"


@dataclass(frozen=True)
class BuiltInProblem:
    """A problem the generic runner can execute.

    `best_known` maps a case id to `{"value", "kind", "justification"}`. It is
    reporting data only: it never reaches the fitness function, the contract or
    the generation prompt, so it cannot influence validity or scoring.
    """

    name: str
    contract: Callable[..., ProblemContract]
    best_known: Mapping[str, Mapping[str, object]] | None = None


PROBLEMS: Mapping[str, BuiltInProblem] = {
    problem.name: problem
    for problem in (
        BuiltInProblem("autocorrelation", autocorrelation_contract),
        BuiltInProblem("bin-packing", bin_packing_contract, BIN_PACKING_BEST_KNOWN),
    )
}


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


def container_limits(contract: ProblemContract) -> ContainerLimits:
    """Mirror the limits `create_evaluator` derives, for use outside the loop."""
    return ContainerLimits(
        memory_mb=contract.resource_limits.memory_mb,
        timeout_seconds=contract.resource_limits.case_time_seconds,
    )


async def recheck_best(
    contract: ProblemContract,
    fitness_function: FitnessFunction,
    source: str,
    limits: ContainerLimits,
) -> dict:
    """Re-run one candidate on every case in a fresh container and rescore it.

    This repeats the work the loop already did, deliberately: a new container run
    and a new call to the trusted fitness function, so a reported score cannot
    reach the summary without being reproduced. Metrics are stringified so exact
    rationals survive JSON.
    """
    cases: dict[str, dict] = {}
    for case in contract.evaluation_suite.cases:
        result = await run_candidate_async(
            source, ENTRY_POINT, case.materialize_inputs(), limits
        )
        if not result.ok:
            cases[case.id] = {
                "ok": False,
                "failure_stage": result.failure_stage,
                "failure_reason": result.failure_reason,
            }
            continue
        fitness = fitness_function.evaluate_case(case, result.output)
        cases[case.id] = {
            "ok": fitness.valid,
            "failure_reason": fitness.failure_reason,
            "metrics": {name: str(value) for name, value in fitness.metrics.items()},
        }
    return cases


def compare_to_best_known(
    recheck: Mapping[str, Mapping[str, object]],
    best_known: Mapping[str, Mapping[str, object]] | None,
    metric_name: str,
) -> dict | None:
    """Report each rechecked metric against its known target, if one exists."""
    if not best_known:
        return None
    cases: dict[str, dict] = {}
    matched = 0
    for case_id, target in best_known.items():
        metrics = (recheck.get(case_id) or {}).get("metrics") or {}
        achieved = metrics.get(metric_name)
        hit = achieved is not None and Fraction(achieved) == Fraction(target["value"])
        matched += int(hit)
        cases[case_id] = {
            "achieved": achieved,
            "target": target["value"],
            "kind": target["kind"],
            "matched": hit,
        }
    return {
        "metric": metric_name,
        "cases": cases,
        "matched_targets": matched,
        "total_targets": len(best_known),
    }


async def run_problem(
    problem: BuiltInProblem,
    *,
    run_dir: Path,
    run_id: str,
    model: str,
    seed: int = 0,
    max_tokens: int = 200_000,
    max_minutes: float = 30.0,
    max_critic_calls: int = 200,
    memory_mb: int = 256,
    contract_kwargs: Mapping[str, object] | None = None,
) -> dict:
    """Run the loop on one built-in problem and return its summary."""
    contract = problem.contract(memory_mb=memory_mb, **(contract_kwargs or {}))
    # Resolving through the registry applies the content-addressed digest check.
    evaluator = create_evaluator(contract)
    fitness_function = evaluator.fitness_function
    provider_budget = ProviderTokenBudget(max_tokens)
    generator = AnthropicProgramGenerator(
        AnthropicGeneratorConfig(model=model, max_concurrency=4, max_attempts=1),
        budget=provider_budget,
    )
    critic = AnthropicCritic(CriticConfig(model=model), budget=provider_budget)
    loop = EvolutionLoop(
        config=EvolutionConfig(
            min_islands=2, max_islands=4, max_batch_size=8,
            pool_size=4, tournament_size=2, random_seed=seed,
            max_tokens_per_request=8_192,
        ),
        limits=EvolutionLimits(
            max_tokens=max_tokens,
            max_time_seconds=max_minutes * 60,
            max_critic_calls=max_critic_calls,
        ),
        generator=generator,
        evaluator=evaluator,
        observer=JsonlObserver(run_dir / "attempts.jsonl"),
        critic=critic,
        require_valid_seed=True,
    )
    try:
        outcome = await loop.run(contract)
    finally:
        await generator.aclose()
        await critic.aclose()

    goal = contract.optimisation_goal
    best = outcome.best_candidate
    summary = {
        "run_id": run_id,
        "problem": problem.name,
        "seed": seed,
        "fitness_function": {
            "id": contract.fitness_function.id,
            "version": contract.fitness_function.version,
            "implementation_sha256": contract.fitness_function.implementation_sha256,
        },
        "evaluator_version": evaluator.version,
        "metric": goal.primary.name,
        "direction": goal.primary.direction,
        "aggregation": goal.aggregation,
        "generator_model": model,
        "critic_model": model,
        "critic_prompt_version": "critic-v1",
        "lean_checked": False,
        "worker_image": evaluator.image,
        "stop_reason": outcome.stop_reason.value,
        "generations": outcome.generations_completed,
        "tokens_used": outcome.tokens_used,
        "best_aggregate_metric": (
            outcome.best_evaluation.metrics.get(goal.primary.name)
            if outcome.best_evaluation else None
        ),
        "best_candidate": best.id if best else None,
    }
    if best is not None:
        recheck = await recheck_best(
            contract, fitness_function, best.source_code, container_limits(contract)
        )
        summary["independent_recheck"] = recheck
        comparison = compare_to_best_known(recheck, problem.best_known, goal.primary.name)
        if comparison is not None:
            summary["best_known_comparison"] = comparison
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str) + "\n")
    return summary
