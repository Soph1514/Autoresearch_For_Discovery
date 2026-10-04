"""LLM-driven evolutionary search over executable ``solve`` programs."""

from .loop import EvolutionLoop
from .models import (
    CandidateDraft,
    CandidateEvaluation,
    EvolutionConfig,
    EvolutionLimits,
    EvolutionOperator,
    EvolutionOutcome,
    EvolutionProtocolError,
    EvolutionState,
    GenerationFailure,
    GenerationRequest,
    GenerationResult,
    ProgramCandidate,
    StopReason,
    TokenUsage,
)
from .ports import CandidateEvaluator, EvolutionObserver, ProgramGenerator, RunCheckpoint

__all__ = [
    "CandidateDraft",
    "CandidateEvaluation",
    "CandidateEvaluator",
    "EvolutionConfig",
    "EvolutionLimits",
    "EvolutionLoop",
    "EvolutionOperator",
    "EvolutionOutcome",
    "EvolutionObserver",
    "EvolutionProtocolError",
    "EvolutionState",
    "GenerationFailure",
    "GenerationRequest",
    "GenerationResult",
    "ProgramCandidate",
    "ProgramGenerator",
    "RunCheckpoint",
    "StopReason",
    "TokenUsage",
]
