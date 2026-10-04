"""Data carried by the evolution loop and its external ports."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Mapping


class EvolutionOperator(StrEnum):
    MUTATE = "mutate"
    CROSSOVER = "crossover"
    DEVELOP_NOVELTY = "develop_novelty"
    REPAIR = "repair"
    RESTART = "restart"


class MutationStrength(StrEnum):
    MICRO = "micro"
    COMPONENT = "component"
    STRUCTURAL = "structural"
    RESTART = "restart"


class SearchMode(StrEnum):
    EXPLOIT = "exploit"
    EXPLORE = "explore"
    EFFICIENCY = "efficiency"
    RADICAL = "radical"


class IslandStatus(StrEnum):
    ACTIVE = "active"
    DORMANT = "dormant"


class CandidateDisposition(StrEnum):
    """Whether a historical candidate remains eligible for search operations."""

    ACTIVE = "active"
    ARCHIVED = "archived"
    DOMINATED = "dominated"
    DUPLICATE = "duplicate"
    UNSAFE = "unsafe"


class StopReason(StrEnum):
    INVALID_SEED = "invalid_seed"
    TIME_LIMIT = "time_limit"
    TOKEN_LIMIT = "token_limit"
    TIME_AND_TOKEN_LIMIT = "time_and_token_limit"
    NO_AFFORDABLE_REQUEST = "no_affordable_request"
    GENERATION_FAILED = "generation_failed"


@dataclass(frozen=True)
class EvolutionConfig:
    min_islands: int = 4
    max_islands: int = 8
    offspring_per_island: int = 2
    max_batch_size: int = 16
    incubation_evaluations: int = 5
    stagnation_evaluations: int = 8
    max_spawns_per_generation: int = 1
    novelty_threshold: float = 0.55
    spawn_novelty_threshold: float = 0.70
    spawn_quality_quantile: float = 0.50
    behavior_novelty_weight: float = 0.70
    lineage_novelty_weight: float = 0.10
    max_novelty_archive_size: int = 128
    max_tokens_per_request: int = 8_192
    pool_size: int = 4
    tournament_size: int = 2
    random_seed: int = 0

    def __post_init__(self) -> None:
        if not 1 <= self.min_islands <= self.max_islands:
            raise ValueError("island limits must satisfy 1 <= min_islands <= max_islands")
        for name in (
            "pool_size",
            "tournament_size",
            "offspring_per_island",
            "max_batch_size",
            "incubation_evaluations",
            "stagnation_evaluations",
            "max_spawns_per_generation",
            "max_novelty_archive_size",
            "max_tokens_per_request",
        ):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        for name in (
            "novelty_threshold",
            "spawn_novelty_threshold",
            "spawn_quality_quantile",
            "behavior_novelty_weight",
            "lineage_novelty_weight",
        ):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")
        if self.behavior_novelty_weight + self.lineage_novelty_weight > 1.0:
            raise ValueError("behavior and lineage novelty weights cannot exceed 1 in total")
        if self.max_batch_size < self.max_islands:
            raise ValueError("max_batch_size must allow one request per possible active island")


@dataclass(frozen=True)
class Assessment:
    """Advisory LLM critique of a valid candidate. Never affects validity or elites."""

    candidate_id: str
    promise_rating: int
    approach_summary: str
    novelty_note: str
    risk_flags: tuple[str, ...]
    model: str
    prompt_version: str

    def __post_init__(self) -> None:
        if type(self.promise_rating) is not int or not 1 <= self.promise_rating <= 5:
            raise ValueError("promise_rating must be an integer from 1 to 5")


@dataclass(frozen=True)
class EvolutionLimits:
    """Whole-run token, active-time, and critic-call limits; the caller supplies the run clock."""

    max_time_seconds: float | None = None
    max_tokens: int | None = None
    max_critic_calls: int | None = None

    def __post_init__(self) -> None:
        if self.max_time_seconds is None and self.max_tokens is None:
            raise ValueError("at least one evolution limit must be configured")
        if self.max_time_seconds is not None:
            if (
                isinstance(self.max_time_seconds, bool)
                or not isinstance(self.max_time_seconds, (int, float))
                or not math.isfinite(self.max_time_seconds)
                or self.max_time_seconds <= 0
            ):
                raise ValueError("max_time_seconds must be positive and finite")
        if self.max_tokens is not None and (
            type(self.max_tokens) is not int or self.max_tokens <= 0
        ):
            raise ValueError("max_tokens must be a positive integer")


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0

    def __post_init__(self) -> None:
        if self.input_tokens < 0 or self.output_tokens < 0:
            raise ValueError("token counts cannot be negative")

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True)
class CandidateDraft:
    hypothesis: str
    predicted_effect: str
    falsification_condition: str
    mechanism_tags: tuple[str, ...]
    source_code: str

    def __post_init__(self) -> None:
        for name in ("hypothesis", "predicted_effect", "falsification_condition"):
            if not getattr(self, name).strip():
                raise ValueError(f"candidate {name} cannot be empty")
        if not self.source_code.strip():
            raise ValueError("candidate source_code cannot be empty")


@dataclass(frozen=True)
class ProgramCandidate:
    id: str
    generation: int
    island_id: str | None
    operator: EvolutionOperator
    parent_ids: tuple[str, ...]
    inspiration_ids: tuple[str, ...]
    hypothesis: str
    predicted_effect: str
    falsification_condition: str
    mechanism_tags: tuple[str, ...]
    source_code: str
    source_fingerprint: str
    request_id: str | None = None
    generation_prompt: str | None = None
    generation_usage: TokenUsage = field(default_factory=TokenUsage)


@dataclass(frozen=True)
class CandidateEvaluation:
    candidate_id: str
    valid: bool
    metrics: Mapping[str, float] = field(default_factory=dict)
    behavioral_descriptor: tuple[float, ...] | None = None
    failure_stage: str | None = None
    failure_reasons: tuple[str, ...] = ()
    passing_cases: int = 0
    total_cases: int = 0
    partial_metrics: Mapping[str, float] = field(default_factory=dict)
    repairable: bool = False
    informative: bool = False
    unsafe: bool = False
    executed: bool = True
    reused_from_candidate_id: str | None = None

    def __post_init__(self) -> None:
        if self.passing_cases < 0 or self.total_cases < 0:
            raise ValueError("case counts cannot be negative")
        if self.passing_cases > self.total_cases:
            raise ValueError("passing_cases cannot exceed total_cases")
        if self.valid and self.unsafe:
            raise ValueError("an unsafe candidate cannot be marked valid")
        if self.reused_from_candidate_id is not None and self.executed:
            raise ValueError("a reused evaluation cannot be marked executed")


@dataclass(frozen=True)
class GenerationRequest:
    id: str
    generation: int
    island_id: str
    operator: EvolutionOperator
    mutation_strength: MutationStrength
    parent_ids: tuple[str, ...]
    inspiration_ids: tuple[str, ...]
    prompt: str


@dataclass(frozen=True)
class GenerationResult:
    request_id: str
    usage: TokenUsage
    draft: CandidateDraft | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if (self.draft is None) == (self.error is None):
            raise ValueError("exactly one of draft or error must be provided")


@dataclass(frozen=True)
class GenerationFailure:
    request_id: str
    generation: int
    error: str
    usage: TokenUsage
    prompt: str


@dataclass(frozen=True)
class NoveltyRecord:
    candidate_id: str
    novelty_score: float
    valid: bool
    repairable: bool
    failure_signature: tuple[str, ...]
    times_selected: int = 0
    last_selected_generation: int | None = None


@dataclass(frozen=True)
class DuplicateRecord:
    candidate_id: str
    canonical_candidate_id: str
    source_fingerprint: str


@dataclass
class IslandState:
    id: str
    elite_id: str | None
    founder_id: str | None
    search_mode: SearchMode
    status: IslandStatus
    created_generation: int
    evaluation_count: int = 0
    trials_since_improvement: int = 0
    protected_for_evaluations: int | None = None
    # Archive cell key -> candidate ID holding that cell. Bounded by pool_size.
    cells: dict[str, str] = field(default_factory=dict)


@dataclass
class EvolutionState:
    generation: int = 0
    next_candidate_number: int = 1
    next_request_number: int = 1
    next_island_number: int = 1
    candidates: dict[str, ProgramCandidate] = field(default_factory=dict)
    evaluations: dict[str, CandidateEvaluation] = field(default_factory=dict)
    active_islands: dict[str, IslandState] = field(default_factory=dict)
    dormant_islands: dict[str, IslandState] = field(default_factory=dict)
    novelty_records: dict[str, NoveltyRecord] = field(default_factory=dict)
    generation_failures: list[GenerationFailure] = field(default_factory=list)
    global_best_id: str | None = None
    total_evaluations: int = 0
    assessments: dict[str, Assessment] = field(default_factory=dict)
    source_index: dict[str, str] = field(default_factory=dict)
    candidate_dispositions: dict[str, CandidateDisposition] = field(default_factory=dict)
    duplicate_records: dict[str, DuplicateRecord] = field(default_factory=dict)


@dataclass(frozen=True)
class EvolutionOutcome:
    best_candidate: ProgramCandidate | None
    best_evaluation: CandidateEvaluation | None
    stop_reason: StopReason
    elapsed_seconds: float
    tokens_used: int
    generations_completed: int
    candidates_generated: int
    candidates_evaluated: int
    active_islands: int
    elite_count: int
    novelty_count: int
    state: EvolutionState


class EvolutionProtocolError(RuntimeError):
    """Raised when an injected generator or evaluator violates its contract."""
