"""LLM-driven evolutionary search over executable ``solve`` programs."""

from .loop import EvolutionLoop
from .models import (
    CandidateDraft,
    CandidateEvaluation,
    EvolutionConfig,
    EvolutionLimits,
    EvolutionOperator,
    EvolutionOutcome,
    GenerationRequest,
    GenerationResult,
    ProgramCandidate,
    StopReason,
    TokenUsage,
)
from .ports import CandidateEvaluator, ProgramGenerator

__all__ = [
    "CandidateDraft",
    "CandidateEvaluation",
    "CandidateEvaluator",
    "EvolutionConfig",
    "EvolutionLimits",
    "EvolutionLoop",
    "EvolutionOperator",
    "EvolutionOutcome",
    "GenerationRequest",
    "GenerationResult",
    "ProgramCandidate",
    "ProgramGenerator",
    "StopReason",
    "TokenUsage",
]
