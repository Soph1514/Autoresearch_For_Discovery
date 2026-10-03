"""Tests for island pools, descriptor cells, and seeded tournament selection."""

from the_pigeon_holes.evolution.engine import EvolutionEngine
from the_pigeon_holes.evolution.models import (
    CandidateEvaluation,
    EvolutionConfig,
    EvolutionOperator,
    ProgramCandidate,
)
from the_pigeon_holes.execution.signature_extractor import MetricGoal, OptimisationGoal

GOAL = OptimisationGoal(MetricGoal("c1", "minimize"), "mean")


def candidate(candidate_id, island_id):
    return ProgramCandidate(
        id=candidate_id,
        generation=1,
        island_id=island_id,
        operator=EvolutionOperator.MUTATE,
        parent_ids=(),
        inspiration_ids=(),
        hypothesis="h",
        predicted_effect="p",
        falsification_condition="f",
        mechanism_tags=("t",),
        source_code=f"# {candidate_id}",
        source_fingerprint=candidate_id,
    )


def valid(candidate_id, c1, cell):
    return CandidateEvaluation(
        candidate_id=candidate_id,
        valid=True,
        metrics={"c1": c1},
        behavioral_descriptor=cell,
        passing_cases=1,
        total_cases=1,
    )


def start(config):
    engine = EvolutionEngine(config)
    seed = candidate("seed", None)
    state = engine.initialise(seed, valid("seed", 5.0, (0, 0)))
    island_id = sorted(state.active_islands)[0]
    return engine, state, island_id


def add(engine, state, island_id, candidate_id, evaluation):
    return engine.apply_generation(
        state, [candidate(candidate_id, island_id)], [evaluation], GOAL
    )


def test_one_representative_per_cell_is_the_best_seen():
    engine, state, island_id = start(EvolutionConfig(min_islands=1, pool_size=4))
    state = add(engine, state, island_id, "worse", valid("worse", 4.0, (1, 0)))
    state = add(engine, state, island_id, "better", valid("better", 3.0, (1, 0)))
    island = state.active_islands[island_id]
    assert island.cells["1,0"] == "better"


def test_pool_is_bounded_and_evicts_the_weakest_cell():
    engine, state, island_id = start(EvolutionConfig(min_islands=1, pool_size=2))
    state = add(engine, state, island_id, "a", valid("a", 3.0, (1, 0)))
    state = add(engine, state, island_id, "b", valid("b", 4.0, (2, 0)))
    island = state.active_islands[island_id]
    assert set(island.cells) == {"1,0", "2,0"}
    assert island.elite_id == "a"


def test_elite_is_the_best_member_of_the_pool():
    engine, state, island_id = start(EvolutionConfig(min_islands=1, pool_size=4))
    state = add(engine, state, island_id, "a", valid("a", 4.5, (1, 0)))
    state = add(engine, state, island_id, "b", valid("b", 3.5, (2, 0)))
    assert state.active_islands[island_id].elite_id == "b"


def test_invalid_candidates_never_enter_the_pool():
    engine, state, island_id = start(EvolutionConfig(min_islands=1, pool_size=4))
    crashed = CandidateEvaluation(
        candidate_id="bad",
        valid=False,
        failure_stage="crash",
        failure_reasons=("boom",),
        repairable=True,
        informative=True,
        total_cases=1,
    )
    state = add(engine, state, island_id, "bad", crashed)
    assert "bad" not in state.active_islands[island_id].cells.values()


def test_tournament_is_reproducible_under_the_same_seed():
    config = EvolutionConfig(min_islands=1, pool_size=4, tournament_size=2, random_seed=11)
    engine_a, state_a, island_a = start(config)
    engine_b, state_b, island_b = start(config)
    for engine, state, island_id in ((engine_a, state_a, island_a), (engine_b, state_b, island_b)):
        for index, cell in enumerate([(1, 0), (2, 0), (3, 0)]):
            state = add(engine, state, island_id, f"c{index}", valid(f"c{index}", 3.0 + index, cell))
    draws_a = [engine_a._tournament(state_a, state_a.active_islands[island_a], GOAL) for _ in range(20)]
    draws_b = [engine_b._tournament(state_b, state_b.active_islands[island_b], GOAL) for _ in range(20)]
    assert draws_a == draws_b


def test_tournament_covering_the_pool_returns_its_best():
    config = EvolutionConfig(min_islands=1, pool_size=4, tournament_size=10, random_seed=3)
    engine, state, island_id = start(config)
    state = add(engine, state, island_id, "best", valid("best", 1.0, (1, 0)))
    state = add(engine, state, island_id, "other", valid("other", 2.0, (2, 0)))
    island = state.active_islands[island_id]
    for _ in range(10):
        assert engine._tournament(state, island, GOAL) == "best"
