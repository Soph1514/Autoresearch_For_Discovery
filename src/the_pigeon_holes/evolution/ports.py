"""External interfaces required by the evolution sub-loop."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol, Sequence

from the_pigeon_holes.models.problem_contract import ProblemContract

from .models import (
    Assessment,
    CandidateEvaluation,
    EvolutionState,
    GenerationFailure,
    GenerationRequest,
    GenerationResult,
    ProgramCandidate,
)

RunCheckpoint = Callable[[], Awaitable[None]]


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


class CandidateCritic(Protocol):
    """Advisory assessor for valid candidates. Returns None when it cannot assess."""

    async def assess(
        self,
        candidate: ProgramCandidate,
        evaluation: CandidateEvaluation,
        problem: ProblemContract,
    ) -> Assessment | None: ...


class EvolutionObserver(Protocol):
    """Synchronous lifecycle sink; implementations must return quickly."""

    def candidate_created(self, candidate: ProgramCandidate) -> None: ...

    def evaluation_started(self, candidate: ProgramCandidate) -> None: ...

    def evaluation_completed(self, evaluation: CandidateEvaluation) -> None: ...

    def generation_failed(self, failure: GenerationFailure) -> None: ...

    def assessment_recorded(self, assessment: Assessment) -> None: ...

    def state_committed(self, state: EvolutionState) -> None: ...
