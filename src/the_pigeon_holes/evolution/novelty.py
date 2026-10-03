"""Inspectable novelty measures for generated programs."""

from __future__ import annotations

import ast
import hashlib
import math
from collections import Counter
from collections.abc import Iterable

from .models import CandidateEvaluation, ProgramCandidate


def source_fingerprint(source_code: str) -> str:
    """Hash a location-independent Python AST, or the raw source if unparsable."""
    try:
        normalized = ast.dump(ast.parse(source_code), include_attributes=False)
    except SyntaxError:
        normalized = source_code.strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def mechanism_distance(left: Iterable[str], right: Iterable[str]) -> float | None:
    """Return Jaccard distance for normalized mechanism tags."""
    left_set = {tag.strip().casefold() for tag in left if tag.strip()}
    right_set = {tag.strip().casefold() for tag in right if tag.strip()}
    if not left_set and not right_set:
        return None
    return 1.0 - len(left_set & right_set) / len(left_set | right_set)


def source_structure_distance(left: str, right: str) -> float | None:
    """Return multiset Jaccard distance over Python AST node types."""
    try:
        left_nodes = Counter(type(node).__name__ for node in ast.walk(ast.parse(left)))
        right_nodes = Counter(type(node).__name__ for node in ast.walk(ast.parse(right)))
    except SyntaxError:
        return None
    union = left_nodes | right_nodes
    if not union:
        return None
    intersection = left_nodes & right_nodes
    return 1.0 - sum(intersection.values()) / sum(union.values())


def behavioral_distance(
    left: tuple[float, ...] | None,
    right: tuple[float, ...] | None,
) -> float | None:
    """Return bounded cosine distance when compatible descriptors are available."""
    if left is None or right is None or not left or len(left) != len(right):
        return None
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0.0 and right_norm == 0.0:
        return 0.0
    if left_norm == 0.0 or right_norm == 0.0:
        return 1.0
    cosine = sum(a * b for a, b in zip(left, right)) / (left_norm * right_norm)
    return min(1.0, max(0.0, (1.0 - cosine) / 2.0))


def failure_distance(
    left: CandidateEvaluation | None,
    right: CandidateEvaluation | None,
) -> float | None:
    """Compare failure stages and reasons when both candidates are invalid."""
    if left is None or right is None or left.valid or right.valid:
        return None
    left_signature = (left.failure_stage, *left.failure_reasons)
    right_signature = (right.failure_stage, *right.failure_reasons)
    return 0.0 if left_signature == right_signature else 1.0


def lineage_distance(left: ProgramCandidate, right: ProgramCandidate) -> float:
    """Estimate lineage separation without requiring a complete ancestry graph."""
    if right.id in left.parent_ids or left.id in right.parent_ids:
        return 0.0
    left_parents = set(left.parent_ids)
    right_parents = set(right.parent_ids)
    if left_parents and right_parents and left_parents & right_parents:
        return 0.25
    return 1.0


def candidate_distance(
    left: ProgramCandidate,
    left_evaluation: CandidateEvaluation | None,
    right: ProgramCandidate,
    right_evaluation: CandidateEvaluation | None,
    *,
    behavior_weight: float,
    lineage_weight: float,
) -> float:
    """Combine inspectable structural, lineage, and evidence distances."""
    if left.source_fingerprint == right.source_fingerprint:
        return 0.0

    semantic_weight = 1.0 - behavior_weight - lineage_weight
    components: list[tuple[float, float]] = [
        (lineage_weight, lineage_distance(left, right))
    ]
    mechanisms = mechanism_distance(left.mechanism_tags, right.mechanism_tags)
    if mechanisms is not None:
        components.append((semantic_weight / 2.0, mechanisms))

    structure = source_structure_distance(left.source_code, right.source_code)
    if structure is not None:
        components.append((semantic_weight / 2.0, structure))

    behavior = behavioral_distance(
        left_evaluation.behavioral_descriptor if left_evaluation else None,
        right_evaluation.behavioral_descriptor if right_evaluation else None,
    )
    if behavior is not None:
        components.append((behavior_weight, behavior))
    else:
        failures = failure_distance(left_evaluation, right_evaluation)
        if failures is not None:
            components.append((behavior_weight, failures))

    components = [(weight, distance) for weight, distance in components if weight > 0.0]
    if not components:
        return 0.0
    total_weight = sum(weight for weight, _ in components)
    return sum(weight * distance for weight, distance in components) / total_weight


def novelty_score(
    candidate: ProgramCandidate,
    evaluation: CandidateEvaluation | None,
    references: Iterable[tuple[ProgramCandidate, CandidateEvaluation | None]],
    *,
    behavior_weight: float,
    lineage_weight: float,
) -> float:
    """Return distance to the nearest reference; an empty archive is maximally novel."""
    distances = [
        candidate_distance(
            candidate,
            evaluation,
            other,
            other_evaluation,
            behavior_weight=behavior_weight,
            lineage_weight=lineage_weight,
        )
        for other, other_evaluation in references
        if other.id != candidate.id
    ]
    return min(distances) if distances else 1.0
