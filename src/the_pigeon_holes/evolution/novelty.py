"""Inspectable novelty measures for generated programs."""

from __future__ import annotations

import ast
import hashlib
import math
from collections import Counter, OrderedDict
from collections.abc import Iterable

from .models import CandidateEvaluation, ProgramCandidate


class NoveltyFeatureCache:
    """Run-local cache for deterministic features reused in novelty comparisons."""

    def __init__(self, max_entries: int = 512) -> None:
        if max_entries <= 0:
            raise ValueError("novelty feature cache max_entries must be positive")
        self.max_entries = max_entries
        self._source_structures: OrderedDict[str, Counter[str] | None] = OrderedDict()
        self._mechanisms: OrderedDict[tuple[str, ...], frozenset[str]] = OrderedDict()
        self._behavior_norms: OrderedDict[tuple[float, ...], float] = OrderedDict()

    def _touch(self, cache, key, value):
        cache[key] = value
        cache.move_to_end(key)
        if len(cache) > self.max_entries:
            cache.popitem(last=False)
        return value

    def source_structure(self, candidate: ProgramCandidate) -> Counter[str] | None:
        if candidate.source_fingerprint not in self._source_structures:
            try:
                value = Counter(
                    type(node).__name__ for node in ast.walk(ast.parse(candidate.source_code))
                )
            except SyntaxError:
                value = None
            return self._touch(
                self._source_structures, candidate.source_fingerprint, value
            )
        value = self._source_structures[candidate.source_fingerprint]
        self._source_structures.move_to_end(candidate.source_fingerprint)
        return value

    def mechanisms(self, tags: tuple[str, ...]) -> frozenset[str]:
        if tags not in self._mechanisms:
            return self._touch(
                self._mechanisms,
                tags,
                frozenset(tag.strip().casefold() for tag in tags if tag.strip()),
            )
        self._mechanisms.move_to_end(tags)
        return self._mechanisms[tags]

    def behavior_norm(self, descriptor: tuple[float, ...]) -> float:
        if descriptor not in self._behavior_norms:
            return self._touch(
                self._behavior_norms,
                descriptor,
                math.sqrt(sum(value * value for value in descriptor)),
            )
        self._behavior_norms.move_to_end(descriptor)
        return self._behavior_norms[descriptor]


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
    feature_cache: NoveltyFeatureCache | None = None,
) -> float:
    """Combine inspectable structural, lineage, and evidence distances."""
    if left.source_fingerprint == right.source_fingerprint:
        return 0.0

    semantic_weight = 1.0 - behavior_weight - lineage_weight
    components: list[tuple[float, float]] = [
        (lineage_weight, lineage_distance(left, right))
    ]
    if feature_cache is None:
        mechanisms = mechanism_distance(left.mechanism_tags, right.mechanism_tags)
    else:
        left_tags = feature_cache.mechanisms(left.mechanism_tags)
        right_tags = feature_cache.mechanisms(right.mechanism_tags)
        mechanisms = (
            None if not left_tags and not right_tags
            else 1.0 - len(left_tags & right_tags) / len(left_tags | right_tags)
        )
    if mechanisms is not None:
        components.append((semantic_weight / 2.0, mechanisms))

    if feature_cache is None:
        structure = source_structure_distance(left.source_code, right.source_code)
    else:
        left_nodes = feature_cache.source_structure(left)
        right_nodes = feature_cache.source_structure(right)
        if left_nodes is None or right_nodes is None:
            structure = None
        else:
            union = left_nodes | right_nodes
            structure = (
                None if not union
                else 1.0 - sum((left_nodes & right_nodes).values()) / sum(union.values())
            )
    if structure is not None:
        components.append((semantic_weight / 2.0, structure))

    left_behavior = left_evaluation.behavioral_descriptor if left_evaluation else None
    right_behavior = right_evaluation.behavioral_descriptor if right_evaluation else None
    if (feature_cache is None or left_behavior is None or right_behavior is None
            or not left_behavior or len(left_behavior) != len(right_behavior)):
        behavior = behavioral_distance(left_behavior, right_behavior)
    else:
        left_norm = feature_cache.behavior_norm(left_behavior)
        right_norm = feature_cache.behavior_norm(right_behavior)
        if left_norm == 0.0 and right_norm == 0.0:
            behavior = 0.0
        elif left_norm == 0.0 or right_norm == 0.0:
            behavior = 1.0
        else:
            cosine = sum(a * b for a, b in zip(left_behavior, right_behavior)) / (
                left_norm * right_norm
            )
            behavior = min(1.0, max(0.0, (1.0 - cosine) / 2.0))
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
    feature_cache: NoveltyFeatureCache | None = None,
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
            feature_cache=feature_cache,
        )
        for other, other_evaluation in references
        if other.id != candidate.id
    ]
    return min(distances) if distances else 1.0
