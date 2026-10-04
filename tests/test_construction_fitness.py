"""Independent objective oracles, adversarial outputs, and generic execution wiring."""

import asyncio
import itertools
import math
from dataclasses import replace

import pytest

from the_pigeon_holes.evaluation.production import SandboxCandidateEvaluator
from the_pigeon_holes.evolution.models import EvolutionOperator, ProgramCandidate
from the_pigeon_holes.execution.container_runner import ContainerLimits, WorkerResult, preflight
from the_pigeon_holes.fitness.registry import builtin_registry
from the_pigeon_holes.models.problem_contract import EvaluationCase, EvaluationSuite, MetricGoal
from the_pigeon_holes.pipeline.runner import PROBLEMS, compare_to_best_known
from the_pigeon_holes.problems.specs import load_instances

NAMES = ("knapsack", "tsp", "max-cut", "makespan")
EXAMPLES = [(name, row) for name in NAMES for row in load_instances(name)]


def constructions(name, inputs):
    """Slow independent reference: enumerate witnesses and objective values."""
    if name == "knapsack":
        for bits in itertools.product((0, 1), repeat=len(inputs["weights"])):
            weight = sum(b * w for b, w in zip(bits, inputs["weights"]))
            if weight <= inputs["capacity"]:
                yield [i for i, bit in enumerate(bits) if bit], sum(
                    b * v for b, v in zip(bits, inputs["values"])
                )
    elif name == "tsp":
        matrix = inputs["distances"]
        # Fixing city 0 removes rotational symmetry without removing any tour.
        for tail in itertools.permutations(range(1, len(matrix))):
            tour = [0, *tail]
            yield tour, matrix[tour[-1]][0] + sum(
                matrix[a][b] for a, b in zip(tour, tour[1:])
            )
    elif name == "max-cut":
        for labels in itertools.product((0, 1), repeat=inputs["n"]):
            left = {i for i, label in enumerate(labels) if label == 0}
            yield list(labels), sum(w for a, b, w in inputs["edges"] if (a in left) != (b in left))
    else:
        for assignment in itertools.product(range(inputs["machines"]), repeat=len(inputs["durations"])):
            yield list(assignment), max(
                sum(duration for label, duration in zip(assignment, inputs["durations"]) if label == machine)
                for machine in range(inputs["machines"])
            )


@pytest.mark.parametrize("name,row", EXAMPLES, ids=[f"{n}/{r['id']}" for n, r in EXAMPLES])
def test_scores_match_independent_oracle_and_stored_optimum(name, row):
    contract = PROBLEMS[name].contract()
    fitness = builtin_registry().resolve(contract.fitness_function)
    fitness.validate_contract(contract)
    case = EvaluationCase(row["id"], row["inputs"])
    metric = contract.optimisation_goal.primary.name
    scores = []
    for witness, expected in constructions(name, row["inputs"]):
        actual = fitness.evaluate_case(case, witness)
        assert actual.valid and actual.metrics == {metric: expected}
        assert type(actual.metrics[metric]) is int
        assert all(math.isfinite(x) for x in actual.behavioral_descriptor)
        scores.append(expected)
    optimum = (max if contract.optimisation_goal.primary.direction == "maximize" else min)(scores)
    assert optimum == row["target"]["value"]
    result = fitness.evaluate_case(case, row["optimal_witness"])
    assert result.metrics == {metric: optimum}
    assert result.evidence["output"] == row["optimal_witness"]
    assert result == fitness.evaluate_case(case, row["optimal_witness"])


@pytest.mark.parametrize("name", NAMES)
def test_baselines_valid_and_search_can_improve(name):
    problem = PROBLEMS[name]
    contract = problem.contract()
    fitness = builtin_registry().resolve(contract.fitness_function)
    namespace = {}
    # Only the checked-in, trusted seed is executed here. Candidates run in Docker.
    exec(contract.seed_program, namespace)
    gaps = []
    for case in contract.evaluation_suite.cases:
        output = namespace["solve"](**case.materialize_inputs())
        result = fitness.evaluate_case(case, output)
        assert result.valid
        metric = contract.optimisation_goal.primary.name
        value, optimum = result.metrics[metric], problem.best_known[case.id]["value"]
        gap = optimum - value if contract.optimisation_goal.primary.direction == "maximize" else value - optimum
        assert gap >= 0
        gaps.append(gap)
    assert any(gap > 0 for gap in gaps)


BAD_OUTPUTS = {
    "knapsack": [[0, 0], [-1], [5], [True], [1.0], [[0]], [0, 1, 2, 3, 4]],
    "tsp": [[0, 1, 2], [0, 1, 2, 3, 0], [0, 1, 2, 2], [0, 1, 2, -1],
            [0, True, 2, 3], [0, 1, 2, 3.0], [[0], 1, 2, 3]],
    "max-cut": [[0, 1], [0, 1, 0, 1], [0, 1, 2], [0, True, 1], [0, 1.0, 0], [0, [], 1]],
    "makespan": [[0], [0, 0, 0, 0, 2], [0, 0, 0, 0, -1], [0, 0, 0, 0, True],
                 [0, 0, 0, 0, 1.0], [0, 0, 0, 0, []]],
}


@pytest.mark.parametrize("name", NAMES)
def test_malformed_and_infeasible_outputs_are_rejected_without_scores(name):
    contract = PROBLEMS[name].contract()
    fitness = builtin_registry().resolve(contract.fitness_function)
    for output in [None, {}, "bad", 1, *BAD_OUTPUTS[name]]:
        result = fitness.evaluate_case(contract.evaluation_suite.cases[0], output)
        assert not result.valid and result.failure_reason and not result.metrics


@pytest.mark.parametrize("name,row", EXAMPLES, ids=[f"{n}/{r['id']}" for n, r in EXAMPLES])
def test_representation_invariance(name, row):
    contract = PROBLEMS[name].contract()
    fitness = builtin_registry().resolve(contract.fitness_function)
    case = EvaluationCase(row["id"], row["inputs"])
    witness = row["optimal_witness"]
    if name == "knapsack":
        alternate = list(reversed(witness))
    elif name == "tsp":
        alternate = list(reversed(witness[1:] + witness[:1]))
    elif name == "max-cut":
        alternate = [1 - x for x in witness]
    else:
        alternate = [row["inputs"]["machines"] - 1 - x for x in witness]
    original = fitness.evaluate_case(case, witness)
    changed = fitness.evaluate_case(case, alternate)
    assert changed.valid and changed.metrics == original.metrics
    assert changed.behavioral_descriptor == original.behavioral_descriptor


BAD_INPUTS = [
    ("knapsack", {"capacity": -1, "weights": [1], "values": [1]}),
    ("knapsack", {"capacity": 1, "weights": [], "values": []}),
    ("knapsack", {"capacity": 1, "weights": [1], "values": []}),
    ("knapsack", {"capacity": 1, "weights": [-1], "values": [1]}),
    ("knapsack", {"capacity": 1, "weights": [1], "values": [-1]}),
    ("knapsack", {"capacity": 10**10, "weights": [1], "values": [1]}),
    ("tsp", {"distances": [[0, 1], [2, 0]]}),
    ("tsp", {"distances": [[0, 1], [1]]}),
    ("tsp", {"distances": [[1, 2], [2, 0]]}),
    ("tsp", {"distances": [[0, -1], [-1, 0]]}),
    ("tsp", {"distances": [[0]]}),
    ("max-cut", {"n": 2, "edges": [[0, 1, 2], [1, 0, 2]]}),
    ("max-cut", {"n": 2, "edges": [[0, 0, 2]]}),
    ("max-cut", {"n": 2, "edges": [[0, 2, 2]]}),
    ("max-cut", {"n": 2, "edges": [[0, 1, -1]]}),
    ("max-cut", {"n": 2, "edges": [[0, 1]]}),
    ("max-cut", {"n": 0, "edges": []}),
    ("makespan", {"machines": 0, "durations": [1]}),
    ("makespan", {"machines": 257, "durations": [1]}),
    ("makespan", {"machines": 2, "durations": []}),
    ("makespan", {"machines": 2, "durations": [0]}),
    ("makespan", {"machines": 2, "durations": [-1]}),
]


@pytest.mark.parametrize("name,inputs", BAD_INPUTS)
def test_invalid_cases_rejected_before_execution(name, inputs):
    contract = PROBLEMS[name].contract()
    fitness = builtin_registry().resolve(contract.fitness_function)
    suite = EvaluationSuite("invalid", (EvaluationCase("invalid", inputs),))
    with pytest.raises(ValueError):
        fitness.validate_contract(replace(contract, evaluation_suite=suite))


@pytest.mark.parametrize("name", NAMES)
def test_wrong_identity_interface_and_goal_are_rejected(name):
    contract = PROBLEMS[name].contract()
    fitness = builtin_registry().resolve(contract.fitness_function)
    with pytest.raises(ValueError, match="reference"):
        fitness.validate_contract(replace(contract, fitness_function=replace(
            contract.fitness_function, implementation_sha256="0" * 64)))
    other = PROBLEMS["makespan" if name == "knapsack" else "knapsack"].contract()
    with pytest.raises(ValueError, match="requires"):
        fitness.validate_contract(replace(other, fitness_function=contract.fitness_function))
    goal = contract.optimisation_goal
    for wrong in (
        replace(goal, primary=MetricGoal("wrong", goal.primary.direction)),
        replace(goal, primary=replace(goal.primary, direction="maximize" if goal.primary.direction == "minimize" else "minimize")),
        replace(goal, aggregation="mean"),
        replace(goal, tie_breakers=(MetricGoal("other", "minimize"),)),
    ):
        with pytest.raises(ValueError, match="requires"):
            fitness.validate_contract(replace(contract, optimisation_goal=wrong))


@pytest.mark.parametrize("name,inputs,output,expected", [
    ("knapsack", {"capacity": 0, "weights": [0, 1], "values": [5, 9]}, [0], 5),
    ("knapsack", {"capacity": 0, "weights": [1], "values": [9]}, [], 0),
    ("tsp", {"distances": [[0, 7], [7, 0]]}, [0, 1], 14),
    ("tsp", {"distances": [[0, 0], [0, 0]]}, [0, 1], 0),
    ("max-cut", {"n": 1, "edges": []}, [0], 0),
    ("max-cut", {"n": 2, "edges": [[0, 1, 0]]}, [0, 1], 0),
    ("makespan", {"machines": 3, "durations": [5]}, [2], 5),
])
def test_boundary_cases(name, inputs, output, expected):
    contract = PROBLEMS[name].contract()
    fitness = builtin_registry().resolve(contract.fitness_function)
    case = EvaluationCase("boundary", inputs)
    fitness.validate_contract(replace(contract, evaluation_suite=EvaluationSuite("boundary", (case,))))
    result = fitness.evaluate_case(case, output)
    assert result.valid and result.metrics[contract.optimisation_goal.primary.name] == expected


def candidate(contract):
    return ProgramCandidate(
        id="seed", generation=0, island_id=None, operator=EvolutionOperator.RESTART,
        parent_ids=(), inspiration_ids=(), hypothesis="baseline", predicted_effect="baseline",
        falsification_condition="invalid", mechanism_tags=("baseline",),
        source_code=contract.seed_program, source_fingerprint="seed",
    )


@pytest.mark.parametrize("name", NAMES)
def test_generic_evaluator_aggregates_and_records_evidence(name, monkeypatch):
    from the_pigeon_holes.evaluation import production
    contract = PROBLEMS[name].contract()
    rows = load_instances(name)

    async def worker(source, entry_point, args, limits, image):
        row = next(row for row in rows if row["inputs"] == args)
        return WorkerResult(True, output=row["optimal_witness"])

    monkeypatch.setattr(production, "run_candidate_async", worker)
    evaluator = SandboxCandidateEvaluator(
        builtin_registry().resolve(contract.fitness_function),
        ContainerLimits(memory_mb=256, timeout_seconds=5),
        max_workers=2, check_daemon=False,
    )
    (result,) = asyncio.run(evaluator.evaluate([candidate(contract)], contract))
    metric = contract.optimisation_goal.primary.name
    assert result.valid and result.passing_cases == len(rows)
    assert result.metrics[metric] == sum(row["target"]["value"] for row in rows)
    evidence = evaluator.evidence["seed"]
    assert evidence["fitness_function"]["implementation_sha256"] == contract.fitness_function.implementation_sha256
    assert set(evidence["cases"]) == {row["id"] for row in rows}
    comparison = compare_to_best_known({
        row["id"]: {"ok": True, "metrics": {metric: str(row["target"]["value"])}}
        for row in rows
    }, PROBLEMS[name].best_known, metric)
    assert comparison["matched_targets"] == len(rows)


@pytest.fixture(scope="module")
def docker_image():
    try:
        return preflight()
    except RuntimeError as error:
        pytest.skip(str(error))


@pytest.mark.parametrize("name", NAMES)
def test_baselines_through_real_sandbox(name, docker_image):
    contract = PROBLEMS[name].contract(case_time_seconds=10, candidate_time_seconds=60)
    evaluator = SandboxCandidateEvaluator(
        builtin_registry().resolve(contract.fitness_function),
        ContainerLimits(memory_mb=256, timeout_seconds=10), image=docker_image, check_daemon=False,
    )
    (result,) = asyncio.run(evaluator.evaluate([candidate(contract)], contract))
    assert result.valid and result.passing_cases == len(contract.evaluation_suite.cases)
