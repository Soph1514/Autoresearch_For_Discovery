"""Deterministic evolutionary planning and population transitions."""

from __future__ import annotations

import copy
import math
import random
from collections.abc import Iterable, Sequence
from functools import cmp_to_key

from the_pigeon_holes.execution.interface_validation import validate_source_signature
from the_pigeon_holes.models.problem_contract import OptimisationGoal, ProblemContract

from .models import (
    CandidateEvaluation,
    EvolutionConfig,
    EvolutionOperator,
    EvolutionProtocolError,
    EvolutionState,
    GenerationRequest,
    IslandState,
    IslandStatus,
    MutationStrength,
    NoveltyRecord,
    ProgramCandidate,
    SearchMode,
)
from .novelty import novelty_score
from .prompting import render_generation_prompt


_SEARCH_MODES = (
    SearchMode.EXPLOIT,
    SearchMode.EXPLORE,
    SearchMode.EFFICIENCY,
    SearchMode.RADICAL,
)


def compare_evaluations(
    left: CandidateEvaluation,
    right: CandidateEvaluation,
    goal: OptimisationGoal,
) -> int:
    """Compare valid evaluations lexicographically under the optimization goal."""
    if left.valid != right.valid:
        return 1 if left.valid else -1
    if not left.valid:
        return 0
    for metric in (goal.primary, *goal.tie_breakers):
        if metric.name not in left.metrics or metric.name not in right.metrics:
            raise EvolutionProtocolError(
                f"valid evaluations must contain configured metric {metric.name!r}"
            )
        left_value = left.metrics[metric.name]
        right_value = right.metrics[metric.name]
        if not math.isfinite(left_value) or not math.isfinite(right_value):
            raise EvolutionProtocolError(
                f"configured metric {metric.name!r} must be finite"
            )
        if left_value == right_value:
            continue
        better = left_value > right_value
        if metric.direction == "minimize":
            better = not better
        return 1 if better else -1
    return 0


class EvolutionEngine:
    """Plan generations and apply completed evidence to in-memory state."""

    def __init__(self, config: EvolutionConfig) -> None:
        self.config = config
        self._random = random.Random(config.random_seed)

    def initialise(
        self,
        seed: ProgramCandidate,
        evaluation: CandidateEvaluation,
    ) -> EvolutionState:
        state = EvolutionState()
        state.candidates[seed.id] = seed
        state.evaluations[seed.id] = evaluation
        state.total_evaluations = 1
        state.next_candidate_number = 1
        if evaluation.valid:
            state.global_best_id = seed.id
        elif self._admit_invalid_novelty(evaluation):
            state.novelty_records[seed.id] = NoveltyRecord(
                candidate_id=seed.id,
                novelty_score=1.0,
                valid=False,
                repairable=evaluation.repairable,
                failure_signature=(
                    evaluation.failure_stage or "unknown",
                    *evaluation.failure_reasons,
                ),
            )

        for index in range(self.config.min_islands):
            island_id = self._new_island_id(state)
            elite_id = seed.id if evaluation.valid else None
            state.active_islands[island_id] = IslandState(
                id=island_id,
                elite_id=elite_id,
                founder_id=elite_id,
                search_mode=_SEARCH_MODES[index % len(_SEARCH_MODES)],
                status=IslandStatus.ACTIVE,
                created_generation=0,
            )
        return state

    def plan_generation(
        self,
        state: EvolutionState,
        problem: ProblemContract,
        affordable_requests: int,
    ) -> tuple[GenerationRequest, ...]:
        active = sorted(state.active_islands.values(), key=lambda island: island.id)
        desired = min(
            len(active) * self.config.offspring_per_island,
            self.config.max_batch_size,
            affordable_requests,
        )
        if desired <= 0 or not active:
            return ()

        allocated = active[:desired]
        while len(allocated) < desired:
            weights = [self._allocation_weight(island, state) for island in active]
            allocated.append(self._random.choices(active, weights=weights, k=1)[0])

        requests = [self._build_request(state, problem, island) for island in allocated]
        return tuple(requests)

    def apply_generation(
        self,
        state: EvolutionState,
        candidates: Sequence[ProgramCandidate],
        evaluations: Sequence[CandidateEvaluation],
        goal: OptimisationGoal,
    ) -> EvolutionState:
        updated = copy.deepcopy(state)
        evaluation_by_id = {evaluation.candidate_id: evaluation for evaluation in evaluations}
        expected = {candidate.id for candidate in candidates}
        if set(evaluation_by_id) != expected or len(evaluation_by_id) != len(evaluations):
            raise EvolutionProtocolError("evaluator must return exactly one result per candidate")

        previous_elites = {
            island_id: island.elite_id for island_id, island in updated.active_islands.items()
        }
        novelty_by_id: dict[str, float] = {}

        for candidate in sorted(candidates, key=lambda item: item.id):
            evaluation = evaluation_by_id[candidate.id]
            updated.candidates[candidate.id] = candidate
            updated.evaluations[candidate.id] = evaluation
            updated.total_evaluations += 1

            island = updated.active_islands.get(candidate.island_id or "")
            if island is not None:
                island.evaluation_count += 1
                island.trials_since_improvement += 1

            references = self._novelty_references(updated, exclude_id=candidate.id)
            novelty = novelty_score(
                candidate,
                evaluation,
                references,
                behavior_weight=self.config.behavior_novelty_weight,
                lineage_weight=self.config.lineage_novelty_weight,
            )
            novelty_by_id[candidate.id] = novelty
            if self._should_admit_novelty(evaluation, novelty):
                updated.novelty_records[candidate.id] = NoveltyRecord(
                    candidate_id=candidate.id,
                    novelty_score=novelty,
                    valid=evaluation.valid,
                    repairable=evaluation.repairable,
                    failure_signature=(
                        evaluation.failure_stage or "unknown",
                        *evaluation.failure_reasons,
                    ),
                )

            if evaluation.valid:
                self._consider_local_elite(updated, candidate, evaluation, goal)
                self._consider_global_best(updated, candidate, evaluation, goal)

        self._make_stagnant_islands_dormant(updated)
        self._spawn_islands(
            updated,
            candidates,
            novelty_by_id,
            previous_elites,
            goal,
        )
        self._prune_novelty_archive(updated)
        updated.generation += 1
        return updated

    def _build_request(
        self,
        state: EvolutionState,
        problem: ProblemContract,
        island: IslandState,
    ) -> GenerationRequest:
        operator = self._choose_operator(state, island)
        parent_ids = self._select_parents(state, island, operator)
        inspiration_ids = self._select_inspirations(state, parent_ids)
        strength = self._mutation_strength(island, operator)
        parents = [
            (state.candidates[candidate_id], state.evaluations.get(candidate_id))
            for candidate_id in parent_ids
        ]
        inspirations = [
            (state.candidates[candidate_id], state.evaluations.get(candidate_id))
            for candidate_id in inspiration_ids
        ]
        request_id = f"request-{state.next_request_number:06d}"
        state.next_request_number += 1
        return GenerationRequest(
            id=request_id,
            generation=state.generation + 1,
            island_id=island.id,
            operator=operator,
            mutation_strength=strength,
            parent_ids=parent_ids,
            inspiration_ids=inspiration_ids,
            prompt=render_generation_prompt(
                problem=problem,
                island=island,
                operator=operator,
                mutation_strength=strength,
                parents=parents,
                inspirations=inspirations,
            ),
        )

    def _choose_operator(
        self,
        state: EvolutionState,
        island: IslandState,
    ) -> EvolutionOperator:
        weights = {
            EvolutionOperator.MUTATE: 0.45,
            EvolutionOperator.CROSSOVER: 0.15,
            EvolutionOperator.DEVELOP_NOVELTY: 0.10,
            EvolutionOperator.REPAIR: 0.15,
            EvolutionOperator.RESTART: 0.15,
        }
        if island.search_mode is SearchMode.EXPLOIT:
            weights[EvolutionOperator.MUTATE] += 0.15
            weights[EvolutionOperator.RESTART] -= 0.05
        elif island.search_mode is SearchMode.EXPLORE:
            weights[EvolutionOperator.DEVELOP_NOVELTY] += 0.10
        elif island.search_mode is SearchMode.RADICAL:
            weights[EvolutionOperator.RESTART] += 0.20
            weights[EvolutionOperator.MUTATE] -= 0.15
        if island.trials_since_improvement >= self.config.stagnation_evaluations:
            weights[EvolutionOperator.RESTART] += 0.25
            weights[EvolutionOperator.MUTATE] = max(
                0.05, weights[EvolutionOperator.MUTATE] - 0.20
            )

        valid_ids = self._valid_candidate_ids(state)
        valid_novelty = self._valid_novelty_ids(state)
        repairable = self._repairable_novelty_ids(state)
        eligible = {
            EvolutionOperator.MUTATE: island.elite_id is not None,
            EvolutionOperator.CROSSOVER: island.elite_id is not None and len(valid_ids) >= 2,
            EvolutionOperator.DEVELOP_NOVELTY: bool(valid_novelty),
            EvolutionOperator.REPAIR: bool(repairable),
            EvolutionOperator.RESTART: True,
        }
        operators = [operator for operator, allowed in eligible.items() if allowed]
        return self._random.choices(
            operators,
            weights=[max(0.0, weights[operator]) for operator in operators],
            k=1,
        )[0]

    def _select_parents(
        self,
        state: EvolutionState,
        island: IslandState,
        operator: EvolutionOperator,
    ) -> tuple[str, ...]:
        if operator is EvolutionOperator.MUTATE:
            return (island.elite_id,) if island.elite_id else ()
        if operator is EvolutionOperator.CROSSOVER and island.elite_id:
            others = [
                candidate_id
                for candidate_id in self._valid_candidate_ids(state)
                if candidate_id != island.elite_id
            ]
            second = self._most_distant(state, island.elite_id, others)
            return (island.elite_id, second) if second else (island.elite_id,)
        if operator is EvolutionOperator.DEVELOP_NOVELTY:
            choices = self._valid_novelty_ids(state)
            return (self._random.choice(choices),) if choices else ()
        if operator is EvolutionOperator.REPAIR:
            choices = self._repairable_novelty_ids(state)
            return (self._random.choice(choices),) if choices else ()
        return ()

    def _select_inspirations(
        self,
        state: EvolutionState,
        parent_ids: tuple[str, ...],
    ) -> tuple[str, ...]:
        ranked = sorted(
            (
                record
                for record in state.novelty_records.values()
                if record.candidate_id not in parent_ids
            ),
            key=lambda record: (-record.novelty_score, record.candidate_id),
        )
        return tuple(record.candidate_id for record in ranked[:2])

    def _mutation_strength(
        self,
        island: IslandState,
        operator: EvolutionOperator,
    ) -> MutationStrength:
        if operator is EvolutionOperator.RESTART:
            return MutationStrength.RESTART
        if island.trials_since_improvement >= self.config.stagnation_evaluations:
            return MutationStrength.STRUCTURAL
        if island.search_mode is SearchMode.EXPLOIT:
            return self._random.choice((MutationStrength.MICRO, MutationStrength.COMPONENT))
        if island.search_mode is SearchMode.RADICAL:
            return MutationStrength.STRUCTURAL
        return MutationStrength.COMPONENT

    def _consider_local_elite(
        self,
        state: EvolutionState,
        candidate: ProgramCandidate,
        evaluation: CandidateEvaluation,
        goal: OptimisationGoal,
    ) -> None:
        island = state.active_islands.get(candidate.island_id or "")
        if island is None:
            return
        incumbent = state.evaluations.get(island.elite_id or "")
        if incumbent is None or compare_evaluations(evaluation, incumbent, goal) > 0:
            island.elite_id = candidate.id
            island.founder_id = island.founder_id or candidate.id
            island.trials_since_improvement = 0

    def _consider_global_best(
        self,
        state: EvolutionState,
        candidate: ProgramCandidate,
        evaluation: CandidateEvaluation,
        goal: OptimisationGoal,
    ) -> None:
        incumbent = state.evaluations.get(state.global_best_id or "")
        if incumbent is None or compare_evaluations(evaluation, incumbent, goal) > 0:
            state.global_best_id = candidate.id

    def _spawn_islands(
        self,
        state: EvolutionState,
        candidates: Sequence[ProgramCandidate],
        novelty_by_id: dict[str, float],
        previous_elites: dict[str, str | None],
        goal: OptimisationGoal,
    ) -> None:
        valid_candidates = [
            candidate
            for candidate in candidates
            if state.evaluations[candidate.id].valid
            and novelty_by_id[candidate.id] >= self.config.spawn_novelty_threshold
        ]
        valid_candidates.sort(
            key=cmp_to_key(
                lambda left, right: -compare_evaluations(
                    state.evaluations[left.id], state.evaluations[right.id], goal
                )
            )
        )
        valid_ids = self._valid_candidate_ids(state)
        ranked_all = sorted(
            valid_ids,
            key=cmp_to_key(
                lambda left, right: -compare_evaluations(
                    state.evaluations[left], state.evaluations[right], goal
                )
            ),
        )
        quality_count = max(1, math.ceil(len(ranked_all) * self.config.spawn_quality_quantile))
        quality_ids = set(ranked_all[:quality_count])

        spawned = 0
        for candidate in valid_candidates:
            if spawned >= self.config.max_spawns_per_generation:
                break
            if candidate.id not in quality_ids and not self._pareto_nondominated(
                state, candidate.id, novelty_by_id, goal
            ):
                continue
            if len(state.active_islands) >= self.config.max_islands:
                self._make_one_island_dormant(state)
            if len(state.active_islands) >= self.config.max_islands:
                break
            source_island = state.active_islands.get(candidate.island_id or "")
            if source_island and source_island.elite_id == candidate.id:
                old_elite = previous_elites.get(source_island.id)
                if old_elite is None:
                    continue
                source_island.elite_id = old_elite
            island_id = self._new_island_id(state)
            state.active_islands[island_id] = IslandState(
                id=island_id,
                elite_id=candidate.id,
                founder_id=candidate.id,
                search_mode=SearchMode.EXPLORE,
                status=IslandStatus.ACTIVE,
                created_generation=state.generation + 1,
                protected_for_evaluations=self.config.incubation_evaluations,
            )
            spawned += 1

    def _pareto_nondominated(
        self,
        state: EvolutionState,
        candidate_id: str,
        batch_novelty: dict[str, float],
        goal: OptimisationGoal,
    ) -> bool:
        evaluation = state.evaluations[candidate_id]
        candidate_novelty = batch_novelty[candidate_id]
        for other_id in self._valid_candidate_ids(state):
            if other_id == candidate_id:
                continue
            comparison = compare_evaluations(state.evaluations[other_id], evaluation, goal)
            other_novelty = batch_novelty.get(
                other_id,
                state.novelty_records.get(
                    other_id, NoveltyRecord(other_id, 0.0, True, False, ())
                ).novelty_score,
            )
            if comparison >= 0 and other_novelty >= candidate_novelty:
                if comparison > 0 or other_novelty > candidate_novelty:
                    return False
        return True

    def _make_stagnant_islands_dormant(self, state: EvolutionState) -> None:
        for island in sorted(
            list(state.active_islands.values()),
            key=lambda item: (-item.trials_since_improvement, item.id),
        ):
            if len(state.active_islands) <= self.config.min_islands:
                return
            if island.trials_since_improvement < self.config.stagnation_evaluations:
                continue
            if island.elite_id == state.global_best_id or self._is_protected(island, state):
                continue
            self._deactivate_island(state, island)

    def _make_one_island_dormant(self, state: EvolutionState) -> None:
        eligible = [
            island
            for island in state.active_islands.values()
            if island.elite_id != state.global_best_id and not self._is_protected(island, state)
        ]
        if not eligible or len(state.active_islands) <= self.config.min_islands:
            return
        selected = max(eligible, key=lambda item: (item.trials_since_improvement, item.id))
        self._deactivate_island(state, selected)

    @staticmethod
    def _deactivate_island(state: EvolutionState, island: IslandState) -> None:
        state.active_islands.pop(island.id)
        island.status = IslandStatus.DORMANT
        state.dormant_islands[island.id] = island

    @staticmethod
    def _is_protected(island: IslandState, state: EvolutionState) -> bool:
        return (
            island.protected_for_evaluations is not None
            and island.evaluation_count < island.protected_for_evaluations
        )

    def _should_admit_novelty(
        self,
        evaluation: CandidateEvaluation,
        novelty: float,
    ) -> bool:
        if evaluation.unsafe or novelty < self.config.novelty_threshold:
            return False
        return evaluation.valid or self._admit_invalid_novelty(evaluation)

    @staticmethod
    def _admit_invalid_novelty(evaluation: CandidateEvaluation) -> bool:
        return not evaluation.unsafe and (evaluation.repairable or evaluation.informative)

    def _novelty_references(
        self,
        state: EvolutionState,
        *,
        exclude_id: str,
    ) -> list[tuple[ProgramCandidate, CandidateEvaluation | None]]:
        ids = {
            island.elite_id
            for island in state.active_islands.values()
            if island.elite_id is not None
        }
        ids.update(state.novelty_records)
        ids.discard(exclude_id)
        return [
            (state.candidates[candidate_id], state.evaluations.get(candidate_id))
            for candidate_id in sorted(ids)
        ]

    def _most_distant(
        self,
        state: EvolutionState,
        anchor_id: str,
        choices: Iterable[str],
    ) -> str | None:
        anchor = state.candidates[anchor_id]
        anchor_evaluation = state.evaluations.get(anchor_id)
        ranked = [
            (
                novelty_score(
                    state.candidates[candidate_id],
                    state.evaluations.get(candidate_id),
                    [(anchor, anchor_evaluation)],
                    behavior_weight=self.config.behavior_novelty_weight,
                    lineage_weight=self.config.lineage_novelty_weight,
                ),
                candidate_id,
            )
            for candidate_id in choices
        ]
        return max(ranked, default=(0.0, None))[1]

    @staticmethod
    def _valid_candidate_ids(state: EvolutionState) -> list[str]:
        return sorted(
            candidate_id
            for candidate_id, evaluation in state.evaluations.items()
            if evaluation.valid
        )

    @staticmethod
    def _valid_novelty_ids(state: EvolutionState) -> list[str]:
        return sorted(
            record.candidate_id for record in state.novelty_records.values() if record.valid
        )

    @staticmethod
    def _repairable_novelty_ids(state: EvolutionState) -> list[str]:
        return sorted(
            record.candidate_id
            for record in state.novelty_records.values()
            if not record.valid and record.repairable
        )

    @staticmethod
    def _allocation_weight(island: IslandState, state: EvolutionState) -> float:
        incubation_bonus = 2.0 if EvolutionEngine._is_protected(island, state) else 0.0
        return 1.0 + incubation_bonus + min(island.trials_since_improvement, 5) * 0.2

    def _prune_novelty_archive(self, state: EvolutionState) -> None:
        excess = len(state.novelty_records) - self.config.max_novelty_archive_size
        if excess <= 0:
            return
        removable = sorted(
            state.novelty_records.values(),
            key=lambda record: (record.novelty_score, record.candidate_id),
        )
        for record in removable[:excess]:
            state.novelty_records.pop(record.candidate_id)

    @staticmethod
    def _new_island_id(state: EvolutionState) -> str:
        island_id = f"island-{state.next_island_number:03d}"
        state.next_island_number += 1
        return island_id
