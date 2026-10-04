"""Contracts for trusted, deterministic problem-specific fitness functions."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Protocol

from the_pigeon_holes.models.problem_contract import (
    EvaluationCase,
    FitnessFunctionRef,
    ProblemContract,
)

FitnessNumber = int | float | Fraction


@dataclass(frozen=True)
class CaseFitness:
    """Validity, objective values, and evidence for one case/output pair."""

    valid: bool
    metrics: Mapping[str, FitnessNumber] = field(default_factory=dict)
    behavioral_descriptor: tuple[float, ...] | None = None
    failure_reason: str | None = None
    evidence: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.valid and self.failure_reason is not None:
            raise ValueError("valid case fitness cannot have a failure reason")
        if not self.valid and not self.failure_reason:
            raise ValueError("invalid case fitness requires a failure reason")
        for name, value in self.metrics.items():
            if not isinstance(name, str) or not name.strip():
                raise ValueError("fitness metric names cannot be empty")
            if isinstance(value, bool) or not isinstance(value, (int, float, Fraction)):
                raise ValueError(f"fitness metric {name!r} must be numeric")
            if not math.isfinite(float(value)):
                raise ValueError(f"fitness metric {name!r} must be finite")
        if self.behavioral_descriptor is not None:
            descriptor = tuple(float(value) for value in self.behavioral_descriptor)
            if not all(math.isfinite(value) for value in descriptor):
                raise ValueError("behavioral descriptor values must be finite")
            object.__setattr__(self, "behavioral_descriptor", descriptor)


class FitnessFunction(Protocol):
    """Trusted scoring logic. Implementations must be deterministic and side-effect free."""

    reference: FitnessFunctionRef

    def validate_contract(self, problem: ProblemContract) -> None: ...

    def evaluate_case(self, case: EvaluationCase, output: object) -> CaseFitness: ...
