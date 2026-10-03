"""Tests for deterministic evolution policy and population transitions."""

from the_pigeon_holes.evolution.engine import (
    EvolutionEngine,
    compare_evaluations,
    validate_source_signature,
)
from the_pigeon_holes.evolution.models import (
    CandidateEvaluation,
    EvolutionConfig,
    EvolutionOperator,
    ProgramCandidate,
)
from the_pigeon_holes.evolution.novelty import source_fingerprint
from the_pigeon_holes.models.problem_contract import (
    EvaluationCase,
    EvaluationSuite,
    InterfaceDefinition,
    MetricGoal,
    OptimisationGoal,
    Parameter,
    ProblemContract,
    ResourceLimits,
)


GOAL = OptimisationGoal(MetricGoal("score", "maximize"), "mean")
CONTRACT = ProblemContract(
    natural_language_spec="Return a high-scoring integer.",
    lean_specification="def solve (x : Int) : Int",
    interface=InterfaceDefinition(
        "python-interface-v1",
        (Parameter("x", "int"),),
        "int",
        "def solve(x: int) -> int:",
    ),
    seed_program="def solve(x: int) -> int:\n    return 0\n",
    evaluation_suite=EvaluationSuite(
        "integer-test", (EvaluationCase("zero", {"x": 0}),)
    ),
    optimisation_goal=GOAL,
    resource_limits=ResourceLimits(1.0, 5.0, 128, 100),
    evaluator_version="test-v1",
)


def _candidate(
    candidate_id: str,
    source: str,
    *,
    island_id: str | None = None,
    parent_ids: tuple[str, ...] = (),
    tags: tuple[str, ...] = ("baseline",),
) -> ProgramCandidate:
    return ProgramCandidate(
        id=candidate_id,
        generation=0 if island_id is None else 1,
        island_id=island_id,
        operator=EvolutionOperator.MUTATE,
        parent_ids=parent_ids,
        inspiration_ids=(),
        hypothesis="test hypothesis",
        predicted_effect="increase score",
        falsification_condition="score does not increase",
        mechanism_tags=tags,
        source_code=source,
        source_fingerprint=source_fingerprint(source),
    )


def _evaluation(
    candidate_id: str,
    score: float,
    *,
    behavior: tuple[float, ...] | None = None,
) -> CandidateEvaluation:
    return CandidateEvaluation(
        candidate_id=candidate_id,
        valid=True,
        metrics={"score": score},
        behavioral_descriptor=behavior,
        passing_cases=1,
        total_cases=1,
    )


def _initial_state(config: EvolutionConfig):
    seed = _candidate("candidate-000000", CONTRACT.seed_program)
    return EvolutionEngine(config).initialise(seed, _evaluation(seed.id, 0.0, behavior=(1.0, 0.0)))


def test_source_validation_requires_exact_synchronous_signature():
    assert validate_source_signature(CONTRACT.seed_program, CONTRACT.solve_signature) is None
    assert "signature" in validate_source_signature(
        "def solve(x: str) -> int:\n    return 0\n", CONTRACT.solve_signature
    )
    assert "synchronous" in validate_source_signature(
        "async def solve(x: int) -> int:\n    return 0\n", CONTRACT.solve_signature
    )


def test_evaluation_comparison_obeys_tie_breakers_and_direction():
    goal = OptimisationGoal(
        MetricGoal("error", "minimize"),
        "mean",
        (MetricGoal("speed", "maximize"),),
    )
    slower = CandidateEvaluation("a", True, {"error": 1.0, "speed": 2.0})
    faster = CandidateEvaluation("b", True, {"error": 1.0, "speed": 3.0})
    lower_error = CandidateEvaluation("c", True, {"error": 0.5, "speed": 0.0})

    assert compare_evaluations(faster, slower, goal) > 0
    assert compare_evaluations(lower_error, faster, goal) > 0


def test_planning_guarantees_each_active_island_one_request_when_affordable():
    config = EvolutionConfig(random_seed=7)
    engine = EvolutionEngine(config)
    state = _initial_state(config)

    requests = engine.plan_generation(state, CONTRACT, affordable_requests=5)

    assert len(requests) == 5
    assert {request.island_id for request in requests} == set(state.active_islands)
    assert all(CONTRACT.solve_signature in request.prompt for request in requests)
    assert all(CONTRACT.lean_specification in request.prompt for request in requests)


def test_valid_novel_candidate_can_found_island_without_stealing_local_elite():
    config = EvolutionConfig(
        min_islands=4,
        max_islands=5,
        novelty_threshold=0.1,
        spawn_novelty_threshold=0.1,
        random_seed=3,
    )
    engine = EvolutionEngine(config)
    state = _initial_state(config)
    source_island = sorted(state.active_islands)[0]
    child = _candidate(
        "candidate-000001",
        "def solve(x: int) -> int:\n    return x + 1\n",
        island_id=source_island,
        parent_ids=("candidate-000000",),
        tags=("constructive", "increment"),
    )

    updated = engine.apply_generation(
        state,
        (child,),
        (_evaluation(child.id, 1.0, behavior=(0.0, 1.0)),),
        GOAL,
    )

    assert len(updated.active_islands) == 5
    assert updated.active_islands[source_island].elite_id == "candidate-000000"
    assert any(
        island.elite_id == child.id and island.id != source_island
        for island in updated.active_islands.values()
    )
    assert updated.global_best_id == child.id


def test_invalid_novelty_is_quarantined_and_unsafe_failure_is_not_archived():
    config = EvolutionConfig(
        novelty_threshold=0.0,
        spawn_novelty_threshold=1.0,
        random_seed=4,
    )
    engine = EvolutionEngine(config)
    state = _initial_state(config)
    island_id = sorted(state.active_islands)[0]
    repairable = _candidate(
        "candidate-000001",
        "def solve(x: int) -> int:\n    return x // 0\n",
        island_id=island_id,
        tags=("division",),
    )
    unsafe = _candidate(
        "candidate-000002",
        "def solve(x: int) -> int:\n    return x * 2\n",
        island_id=island_id,
        tags=("unsafe-external",),
    )
    evaluations = (
        CandidateEvaluation(
            repairable.id,
            valid=False,
            failure_stage="execution",
            failure_reasons=("division by zero",),
            repairable=True,
            informative=True,
        ),
        CandidateEvaluation(
            unsafe.id,
            valid=False,
            failure_stage="safety",
            failure_reasons=("forbidden operation",),
            unsafe=True,
        ),
    )

    updated = engine.apply_generation(state, (repairable, unsafe), evaluations, GOAL)

    assert repairable.id in updated.novelty_records
    assert unsafe.id not in updated.novelty_records
    assert updated.active_islands[island_id].elite_id == "candidate-000000"
    assert updated.global_best_id == "candidate-000000"
