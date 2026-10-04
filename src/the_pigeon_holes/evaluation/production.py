"""Stage 0 evaluator for the first autocorrelation inequality.

Candidates run in containers. The host validates each output with the exact
judge and computes the objective. No candidate code runs on the host.
"""

from __future__ import annotations

import asyncio
from fractions import Fraction
from dataclasses import replace
from typing import Sequence

from the_pigeon_holes.evolution.models import CandidateEvaluation, ProgramCandidate
from the_pigeon_holes.execution.container_runner import (
    DEFAULT_IMAGE,
    ContainerLimits,
    preflight,
    run_candidate_async,
)
from the_pigeon_holes.execution.interface_validation import validate_source_signature
from the_pigeon_holes.judging.autocorrelation import (
    JUDGE_VERSION,
    MIN_POINTS,
    MAX_POINTS,
    InvalidOutput,
    c1,
    descriptor_cell,
    validate_output,
)
from the_pigeon_holes.models.problem_contract import ProblemContract

ENTRY_POINT = "solve"
PRIMARY_METRIC = "c1"
REPAIRABLE_STAGES = frozenset({"static_validation", "crash", "invalid_output"})


class AutocorrelationEvaluator:
    """Implements `CandidateEvaluator` for the autocorrelation family."""

    def __init__(
        self,
        limits: ContainerLimits,
        *,
        image: str = DEFAULT_IMAGE,
        max_workers: int = 4,
        check_daemon: bool = True,
    ) -> None:
        if type(max_workers) is not int or max_workers <= 0:
            raise ValueError('max_workers must be a positive integer')
        if check_daemon:
            image = preflight(image)
        self.limits = limits
        self.image = image
        self._semaphore = asyncio.Semaphore(max_workers)

    async def evaluate(
        self,
        candidates: Sequence[ProgramCandidate],
        problem: ProblemContract,
    ) -> Sequence[CandidateEvaluation]:
        validate_contract(problem)

        async def evaluate_one(candidate: ProgramCandidate) -> CandidateEvaluation:
            async with self._semaphore:
                try:
                    async with asyncio.timeout(problem.resource_limits.candidate_time_seconds):
                        return await self._evaluate_one(candidate, problem)
                except TimeoutError:
                    return _invalid(candidate, 'timeout', 'candidate-suite wall-clock limit',
                                    len(problem.evaluation_suite.cases))

        tasks = [asyncio.create_task(evaluate_one(candidate)) for candidate in candidates]
        try:
            return tuple(await asyncio.gather(*tasks))
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _evaluate_one(
        self, candidate: ProgramCandidate, problem: ProblemContract,
    ) -> CandidateEvaluation:
        total = len(problem.evaluation_suite.cases)
        signature_error = validate_source_signature(
            candidate.source_code, problem.solve_signature
        )
        if signature_error:
            return _invalid(candidate, "static_validation", signature_error, total)

        values: list[Fraction] = []
        cells: list[tuple[int, int]] = []
        for case in problem.evaluation_suite.cases:
            args = case.materialize_inputs()
            limits = replace(self.limits,
                timeout_seconds=min(self.limits.timeout_seconds, problem.resource_limits.case_time_seconds),
                memory_mb=min(self.limits.memory_mb, problem.resource_limits.memory_mb))
            result = await run_candidate_async(
                candidate.source_code, ENTRY_POINT, args, limits, self.image
            )
            if not result.ok:
                return _invalid(candidate, result.failure_stage, result.failure_reason, total)
            try:
                output = validate_output(result.output)
                if len(output) != args["n"]:
                    raise InvalidOutput(
                        f"expected length {args['n']}, got {len(output)}"
                    )
                value, cell = await asyncio.to_thread(_score, output)
                values.append(value)
                cells.append(cell)
            except InvalidOutput as error:
                return _invalid(candidate, "invalid_output", str(error), total)

        mean = sum(values, Fraction(0)) / len(values)
        return CandidateEvaluation(
            candidate_id=candidate.id,
            valid=True,
            metrics={PRIMARY_METRIC: float(mean)},
            behavioral_descriptor=tuple(float(part) for part in cells[0]),
            passing_cases=len(values),
            total_cases=total,
        )


def _invalid(
    candidate: ProgramCandidate,
    stage: str | None,
    reason: str | None,
    total: int,
) -> CandidateEvaluation:
    stage = stage or "crash"
    return CandidateEvaluation(
        candidate_id=candidate.id,
        valid=False,
        failure_stage=stage,
        failure_reasons=(reason or stage,),
        repairable=stage in REPAIRABLE_STAGES,
        informative=True,
        total_cases=total,
    )


def _score(output):
    return c1(output), descriptor_cell(output)


def validate_contract(problem: ProblemContract) -> None:
    """Reject families this versioned judge cannot evaluate; never reinterpret metrics."""
    if problem.evaluator_version != JUDGE_VERSION:
        raise ValueError(f'Unsupported evaluator_version; this evaluator requires {JUDGE_VERSION!r}.')
    interface = problem.interface
    if ([(p.name, p.python_type) for p in interface.parameters] != [('n', 'int')]
            or interface.return_type != 'list[int]' or interface.supporting_types_code.strip()):
        raise ValueError('Autocorrelation requires solve(n: int) -> list[int] without supporting types.')
    goal = problem.optimisation_goal
    if (goal.primary.name != PRIMARY_METRIC or goal.primary.direction != 'minimize'
            or goal.aggregation != 'mean' or goal.tie_breakers):
        raise ValueError('Autocorrelation requires mean c1 minimization without tie-breakers.')
    for case in problem.evaluation_suite.cases:
        n = case.inputs.get('n')
        if type(n) is not int or not MIN_POINTS <= n <= MAX_POINTS:
            raise ValueError(f'Autocorrelation case n must be between {MIN_POINTS} and {MAX_POINTS}.')


def create_evaluator(problem: ProblemContract) -> AutocorrelationEvaluator:
    """Default trusted factory used by the UI; Docker preflight must succeed."""
    validate_contract(problem)
    return AutocorrelationEvaluator(ContainerLimits(
        memory_mb=problem.resource_limits.memory_mb,
        timeout_seconds=problem.resource_limits.case_time_seconds,
    ))
