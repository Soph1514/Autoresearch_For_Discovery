"""Generic sandbox execution backed by a trusted problem fitness function."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from fractions import Fraction
from statistics import median
from typing import Sequence

from the_pigeon_holes.evolution.models import CandidateEvaluation, ProgramCandidate
from the_pigeon_holes.execution.container_runner import (
    DEFAULT_IMAGE, ContainerLimits, preflight, run_candidate_async,
)
from the_pigeon_holes.execution.interface_validation import validate_source_signature
from the_pigeon_holes.fitness.base import FitnessFunction, FitnessNumber
from the_pigeon_holes.fitness.registry import FitnessFunctionRegistry, configured_registry
from the_pigeon_holes.models.problem_contract import MetricGoal, ProblemContract

ENTRY_POINT = "solve"
EVALUATOR_VERSION = "sandbox-fitness-v1"
REPAIRABLE_STAGES = frozenset({"static_validation", "crash", "invalid_output"})


class SandboxCandidateEvaluator:
    """Run candidates in containers and score outputs with trusted fitness logic."""

    version = EVALUATOR_VERSION

    def __init__(self, fitness_function: FitnessFunction, limits: ContainerLimits, *,
                 image: str = DEFAULT_IMAGE, max_workers: int = 4,
                 check_daemon: bool = True) -> None:
        if type(max_workers) is not int or max_workers <= 0:
            raise ValueError("max_workers must be a positive integer")
        if check_daemon:
            image = preflight(image)
        self.fitness_function = fitness_function
        self.limits = limits
        self.image = image
        self._semaphore = asyncio.Semaphore(max_workers)
        self.evidence: dict[str, dict] = {}

    async def evaluate(self, candidates: Sequence[ProgramCandidate],
                       problem: ProblemContract) -> Sequence[CandidateEvaluation]:
        self.fitness_function.validate_contract(problem)

        async def evaluate_one(candidate: ProgramCandidate) -> CandidateEvaluation:
            try:
                async with asyncio.timeout(problem.resource_limits.candidate_time_seconds):
                    return await self._evaluate_one(candidate, problem)
            except TimeoutError:
                return _invalid(candidate, "timeout", "candidate-suite wall-clock limit",
                                len(problem.evaluation_suite.cases))

        tasks = [asyncio.create_task(evaluate_one(candidate)) for candidate in candidates]
        try:
            return tuple(await asyncio.gather(*tasks))
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _evaluate_one(self, candidate: ProgramCandidate,
                            problem: ProblemContract) -> CandidateEvaluation:
        total = len(problem.evaluation_suite.cases)
        signature_error = validate_source_signature(candidate.source_code, problem.solve_signature)
        if signature_error:
            return _invalid(candidate, "static_validation", signature_error, total)

        reference = self.fitness_function.reference
        record = {
            "evaluator_version": self.version,
            "fitness_function": {
                "id": reference.id, "version": reference.version,
                "implementation_sha256": reference.implementation_sha256,
            },
            "image": self.image,
            "cases": {},
        }
        self.evidence[candidate.id] = record

        async def evaluate_case(case):
            arguments = case.materialize_inputs()
            case_record = {"inputs": arguments}
            record["cases"][case.id] = case_record
            limits = replace(
                self.limits,
                timeout_seconds=min(self.limits.timeout_seconds,
                                    problem.resource_limits.case_time_seconds),
                memory_mb=min(self.limits.memory_mb, problem.resource_limits.memory_mb),
            )
            async with self._semaphore:
                result = await run_candidate_async(
                    candidate.source_code, ENTRY_POINT, arguments, limits, self.image
                )
                case_record.update(ok=result.ok, failure_stage=result.failure_stage,
                                   failure_reason=result.failure_reason)
                if not result.ok:
                    return (_invalid(candidate, result.failure_stage,
                                     result.failure_reason, total), None)

                # Bound trusted host-side scoring as well as container execution.
                case_fitness = await asyncio.to_thread(
                    self.fitness_function.evaluate_case, case, result.output
                )
                case_record["fitness_evidence"] = dict(case_fitness.evidence)
                if not case_fitness.valid:
                    case_record.update(ok=False, failure_stage="invalid_output",
                                       failure_reason=case_fitness.failure_reason)
                    return (_invalid(candidate, "invalid_output",
                                     case_fitness.failure_reason, total), None)
                return None, case_fitness

        tasks = [asyncio.create_task(evaluate_case(case))
                 for case in problem.evaluation_suite.cases]
        try:
            results = await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

        case_fitnesses = []
        for failure, case_fitness in results:
            if failure is not None:
                return failure
            assert case_fitness is not None
            case_fitnesses.append(case_fitness)

        goals = (problem.optimisation_goal.primary,
                 *problem.optimisation_goal.tie_breakers)
        aggregated: dict[str, FitnessNumber] = {}
        for goal in goals:
            try:
                values = [fitness.metrics[goal.name] for fitness in case_fitnesses]
            except KeyError as exc:
                raise RuntimeError(
                    f"fitness function omitted configured metric {goal.name!r}"
                ) from exc
            aggregated[goal.name] = _aggregate(
                values, problem.optimisation_goal.aggregation, goal
            )

        record["aggregate_metrics_exact"] = {
            name: _exact_evidence(value) for name, value in aggregated.items()
        }
        descriptor = next(
            (fitness.behavioral_descriptor for fitness in case_fitnesses
             if fitness.behavioral_descriptor is not None), None
        )
        return CandidateEvaluation(
            candidate_id=candidate.id, valid=True,
            metrics={name: float(value) for name, value in aggregated.items()},
            behavioral_descriptor=descriptor,
            passing_cases=len(case_fitnesses), total_cases=total,
        )


def _aggregate(values: Sequence[FitnessNumber], aggregation: str,
               goal: MetricGoal) -> FitnessNumber:
    if aggregation == "sum":
        return sum(values)
    if aggregation == "mean":
        return sum(values) / len(values)
    if aggregation == "median":
        return median(values)
    if aggregation == "worst_case":
        return min(values) if goal.direction == "maximize" else max(values)
    raise RuntimeError(f"unsupported metric aggregation {aggregation!r}")


def _exact_evidence(value: FitnessNumber) -> dict[str, str]:
    if isinstance(value, Fraction):
        exact = value
    elif isinstance(value, int):
        exact = Fraction(value)
    else:
        exact = Fraction.from_float(value)
    return {"numerator": str(exact.numerator),
            "denominator": str(exact.denominator)}


def _invalid(candidate: ProgramCandidate, stage: str | None,
             reason: str | None, total: int) -> CandidateEvaluation:
    stage = stage or "crash"
    return CandidateEvaluation(
        candidate_id=candidate.id, valid=False, failure_stage=stage,
        failure_reasons=(reason or stage,), repairable=stage in REPAIRABLE_STAGES,
        informative=True, total_cases=total,
    )


def create_evaluator(problem: ProblemContract, *,
                     registry: FitnessFunctionRegistry | None = None
                     ) -> SandboxCandidateEvaluator:
    """Resolve the required trusted fitness function and prepare sandbox execution."""
    active_registry = registry or configured_registry()
    fitness_function = active_registry.resolve(problem.fitness_function)
    fitness_function.validate_contract(problem)
    return SandboxCandidateEvaluator(
        fitness_function,
        ContainerLimits(memory_mb=problem.resource_limits.memory_mb,
                        timeout_seconds=problem.resource_limits.case_time_seconds),
    )
