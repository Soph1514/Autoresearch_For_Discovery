"""Stage 0 evaluator for the first autocorrelation inequality.

Candidates run in containers. The host validates each output with the exact
judge and computes the objective. No candidate code runs on the host.
"""

from __future__ import annotations

import asyncio
from fractions import Fraction
from typing import Sequence

from the_pigeon_holes.evolution.models import CandidateEvaluation, ProgramCandidate
from the_pigeon_holes.execution.container_runner import (
    DEFAULT_IMAGE,
    ContainerLimits,
    preflight,
    run_candidate,
)
from the_pigeon_holes.execution.interface_validation import validate_source_signature
from the_pigeon_holes.judging.autocorrelation import (
    JUDGE_VERSION,
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
        if check_daemon:
            preflight(image)
        self.limits = limits
        self.image = image
        self._semaphore = asyncio.Semaphore(max_workers)

    async def evaluate(
        self,
        candidates: Sequence[ProgramCandidate],
        problem: ProblemContract,
    ) -> Sequence[CandidateEvaluation]:
        if problem.evaluator_version != JUDGE_VERSION:
            raise ValueError(
                f"contract evaluator_version {problem.evaluator_version!r} "
                f"does not match judge {JUDGE_VERSION!r}"
            )

        async def evaluate_one(candidate: ProgramCandidate) -> CandidateEvaluation:
            async with self._semaphore:
                return await asyncio.to_thread(self._evaluate_sync, candidate, problem)

        return tuple(await asyncio.gather(*(evaluate_one(c) for c in candidates)))

    def _evaluate_sync(
        self,
        candidate: ProgramCandidate,
        problem: ProblemContract,
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
            result = run_candidate(
                candidate.source_code, ENTRY_POINT, args, self.limits, self.image
            )
            if not result.ok:
                return _invalid(candidate, result.failure_stage, result.failure_reason, total)
            try:
                output = validate_output(result.output)
                if len(output) != args["n"]:
                    raise InvalidOutput(
                        f"expected length {args['n']}, got {len(output)}"
                    )
                values.append(c1(output))
                cells.append(descriptor_cell(output))
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
