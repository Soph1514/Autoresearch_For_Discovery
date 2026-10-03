"""External interfaces required by the evolution sub-loop."""

from __future__ import annotations

from typing import Protocol, Sequence

from the_pigeon_holes.models.problem_contract import ProblemContract

from .models import (
    CandidateEvaluation,
    GenerationRequest,
    GenerationResult,
    ProgramCandidate,
)


class ProgramGenerator(Protocol):
    async def generate(
        self,
        requests: Sequence[GenerationRequest],
    ) -> Sequence[GenerationResult]: ...


class CandidateEvaluator(Protocol):
    async def evaluate(
        self,
        candidates: Sequence[ProgramCandidate],
        problem: ProblemContract,
    ) -> Sequence[CandidateEvaluation]: ...
