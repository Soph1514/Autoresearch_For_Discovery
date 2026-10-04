"""Tests for the exact bin-packing fitness function and its provable instances.

Each instance's optimum is a theorem about the construction rather than a number
copied from a benchmark table: the items form disjoint triples that each sum to
exactly the capacity, so one bin per triple is feasible, and the volume bound
ceil(sum(sizes) / capacity) equals the triple count, so nothing smaller is. These
tests re-derive both halves of that argument instead of trusting ``BEST_KNOWN``.
"""

import pytest

from the_pigeon_holes.execution.signature_extractor import (
    MetricGoal,
    OptimisationGoal,
    Parameter,
)
from problems.bin_packing.fitness import (
    BIN_PACKING_FITNESS_REF,
    EXCESS_CAP,
    FILL_BINS,
    FITNESS_FUNCTION_ID,
    FITNESS_FUNCTION_VERSION,
    BinPackingFitnessFunction,
    InvalidOutput,
    bin_loads,
    bins_used,
    descriptor_cell,
    lower_bound,
    validate_assignment,
)
from the_pigeon_holes.models.problem_contract import (
    EvaluationCase,
    EvaluationSuite,
    InterfaceDefinition,
    ProblemContract,
    ResourceLimits,
)
from the_pigeon_holes.problems.bin_packing import (
    BEST_KNOWN,
    CAPACITY,
    INSTANCES,
    SEED_SOURCE,
    bin_packing_contract,
    optimal_assignment,
    triplet_groups,
    triplet_sizes,
)

FITNESS = BinPackingFitnessFunction()

# A hand-checkable instance: two bins of 5 + 3 + 2 fill a capacity of 10 exactly.
HAND_CAPACITY = 10
HAND_SIZES = [5, 3, 2, 5, 3, 2]


def seed_solver():
    """Compile the contract's baseline so its behaviour can be measured."""
    namespace: dict = {}
    exec(SEED_SOURCE, namespace)
    return namespace["solve"]


def instance(triples, seed):
    """Return the shuffled item sizes and a packing attaining the optimum."""
    return triplet_sizes(triples, seed=seed), optimal_assignment(triples, seed=seed)


# --- The construction the optimum rests on ---------------------------------------


@pytest.mark.parametrize("case_id,triples,seed", INSTANCES)
def test_every_triple_sums_to_the_capacity(case_id, triples, seed):
    groups = triplet_groups(triples, seed=seed)
    assert len(groups) == triples
    for group in groups:
        assert sum(group) == CAPACITY
        assert group[0] > group[1] > group[2] >= 1
        # No size reaches half the capacity, so no two items of a triple pair up.
        assert 2 * group[0] < CAPACITY


@pytest.mark.parametrize("case_id,triples,seed", INSTANCES)
def test_items_are_exactly_the_shuffled_triples(case_id, triples, seed):
    sizes = triplet_sizes(triples, seed=seed)
    groups = triplet_groups(triples, seed=seed)
    assert sorted(sizes) == sorted(size for group in groups for size in group)
    assert sum(sizes) == triples * CAPACITY


def test_instance_generation_is_deterministic():
    assert triplet_sizes(10, seed=0) == triplet_sizes(10, seed=0)
    assert triplet_groups(10, seed=0) == triplet_groups(10, seed=0)
    assert triplet_sizes(10, seed=0) != triplet_sizes(10, seed=1)


# --- Known-answer oracles --------------------------------------------------------


@pytest.mark.parametrize("case_id,triples,seed", INSTANCES)
def test_stored_optimum_is_both_necessary_and_attained(case_id, triples, seed):
    sizes, optimal = instance(triples, seed)
    # Necessary: no feasible assignment can beat the volume bound.
    assert lower_bound(CAPACITY, sizes) == triples
    # Attained: the construction's own packing uses exactly that many bins.
    assert bins_used(optimal, CAPACITY, sizes) == triples
    assert BEST_KNOWN[case_id] == {
        "value": triples,
        "kind": "optimal",
        "justification": BEST_KNOWN[case_id]["justification"],
    }


@pytest.mark.parametrize("case_id,triples,seed", INSTANCES)
def test_optimal_packing_leaves_no_slack(case_id, triples, seed):
    sizes, optimal = instance(triples, seed)
    loads = bin_loads(optimal, sizes)
    assert set(loads.values()) == {CAPACITY}


def test_exact_value_for_small_hand_case():
    assert lower_bound(HAND_CAPACITY, HAND_SIZES) == 2
    assert bins_used([0, 0, 0, 1, 1, 1], HAND_CAPACITY, HAND_SIZES) == 2
    # Interleaved but still two full bins: 5+2+3 and 3+5+2.
    assert bins_used([0, 1, 0, 1, 0, 1], HAND_CAPACITY, HAND_SIZES) == 2


def test_evaluate_case_reports_the_optimum_and_its_bound():
    case_id, triples, seed = INSTANCES[0]
    sizes, optimal = instance(triples, seed)
    case = EvaluationCase(case_id, {"capacity": CAPACITY, "sizes": sizes})
    fitness = FITNESS.evaluate_case(case, optimal)
    assert fitness.valid and fitness.failure_reason is None
    assert fitness.metrics == {"bins_used": triples}
    assert fitness.evidence["lower_bound"] == triples
    assert fitness.evidence["bins_used_exact"] == {"numerator": str(triples), "denominator": "1"}
    # "output" is the shared witness key the generic recheck tooling looks for.
    assert fitness.evidence["output"] == optimal


# --- The baseline must leave something to improve --------------------------------


@pytest.mark.parametrize("case_id,triples,seed", INSTANCES)
def test_seed_baseline_is_valid_but_strictly_worse_than_optimal(case_id, triples, seed):
    sizes, _ = instance(triples, seed)
    assignment = seed_solver()(CAPACITY, sizes)
    assert bins_used(assignment, CAPACITY, sizes) > triples


def test_seed_matches_the_contract_signature():
    contract = bin_packing_contract()
    assert contract.solve_signature == "def solve(capacity: int, sizes: list[int]) -> list[int]:"


# --- Rejection -------------------------------------------------------------------


@pytest.mark.parametrize("bad", [
    "not a list",
    None,
    42,
    {0: 1},
    [0, 0, 0, 1, 1],                 # one index short
    [0, 0, 0, 1, 1, 1, 1],           # one index too many
    [0, 0, 0, 1, 1, True],           # bool is not an int here
    [0, 0, 0, 1, 1, 1.0],            # float index
    [0, 0, 0, 1, 1, -1],             # negative index
])
def test_invalid_outputs_are_rejected(bad):
    with pytest.raises(InvalidOutput):
        validate_assignment(bad, HAND_CAPACITY, HAND_SIZES)


def test_tuple_output_is_accepted():
    assert validate_assignment((0, 0, 0, 1, 1, 1), HAND_CAPACITY, HAND_SIZES) == [0, 0, 0, 1, 1, 1]


def test_overfull_bins_are_rejected():
    with pytest.raises(InvalidOutput, match="capacity"):
        validate_assignment([0] * 6, HAND_CAPACITY, HAND_SIZES)


def test_invalid_case_fitness_carries_a_reason():
    case = EvaluationCase("hand", {"capacity": HAND_CAPACITY, "sizes": HAND_SIZES})
    fitness = FITNESS.evaluate_case(case, [0] * 6)
    assert not fitness.valid
    assert fitness.failure_reason
    assert fitness.metrics == {}


def test_failure_reasons_never_quote_the_capacity_or_item_sizes():
    """Reasons reach generation as repair feedback, so they must stay instance-free."""
    case = EvaluationCase("secret", {"capacity": 997, "sizes": [613, 251, 233]})
    fitness = FITNESS.evaluate_case(case, [0, 0, 0])
    assert not fitness.valid
    for secret in ("997", "613", "251", "233"):
        assert secret not in fitness.failure_reason


# --- Invariance and determinism --------------------------------------------------


def test_relabelling_bins_does_not_change_the_score():
    base = bins_used([0, 0, 0, 1, 1, 1], HAND_CAPACITY, HAND_SIZES)
    assert bins_used([1, 1, 1, 0, 0, 0], HAND_CAPACITY, HAND_SIZES) == base
    assert bins_used([7, 7, 7, 3, 3, 3], HAND_CAPACITY, HAND_SIZES) == base


def test_repeated_evaluation_is_identical():
    case_id, triples, seed = INSTANCES[0]
    sizes, optimal = instance(triples, seed)
    case = EvaluationCase(case_id, {"capacity": CAPACITY, "sizes": sizes})
    first, second = (FITNESS.evaluate_case(case, optimal) for _ in range(2))
    assert first.metrics == second.metrics
    assert first.behavioral_descriptor == second.behavioral_descriptor


# --- Planted bugs ----------------------------------------------------------------


def test_relabelling_invariance_catches_a_bug_the_known_answer_misses():
    """`max(indices) + 1` scores the optimum right but breaks on non-contiguous bins.

    This is why both oracles exist: the known-answer check alone would accept it.
    """
    planted = lambda assignment: max(assignment) + 1
    contiguous, gapped = [0, 0, 0, 1, 1, 1], [0, 0, 0, 5, 5, 5]
    assert planted(contiguous) == bins_used(contiguous, HAND_CAPACITY, HAND_SIZES)
    assert planted(gapped) != bins_used(gapped, HAND_CAPACITY, HAND_SIZES)


def test_known_answer_catches_a_planted_item_count_bug():
    """Counting items instead of bins passes every type check and is still wrong."""
    sizes, optimal = instance(*INSTANCES[0][1:])
    assert bins_used(optimal, CAPACITY, sizes) == INSTANCES[0][1]
    assert len(optimal) != INSTANCES[0][1]


# --- Descriptors -----------------------------------------------------------------


@pytest.mark.parametrize("case_id,triples,seed", INSTANCES)
def test_descriptors_are_deterministic_and_bounded(case_id, triples, seed):
    sizes, optimal = instance(triples, seed)
    for assignment in (optimal, seed_solver()(CAPACITY, sizes)):
        cell = descriptor_cell(assignment, CAPACITY, sizes)
        assert cell == descriptor_cell(assignment, CAPACITY, sizes)
        assert 0 <= cell[0] <= EXCESS_CAP
        assert 0 <= cell[1] < FILL_BINS


@pytest.mark.parametrize("case_id,triples,seed", INSTANCES)
def test_optimal_packing_lands_in_the_zero_excess_fullest_cell(case_id, triples, seed):
    sizes, optimal = instance(triples, seed)
    assert descriptor_cell(optimal, CAPACITY, sizes) == (
        0,
        FILL_BINS - 1,
    )


# --- Contract admission ----------------------------------------------------------


def test_builtin_contract_is_accepted():
    FITNESS.validate_contract(bin_packing_contract())


def test_identity_and_version_are_pinned():
    assert FITNESS_FUNCTION_ID == "bin-packing"
    assert FITNESS_FUNCTION_VERSION == "exact-v1"
    assert FITNESS.reference == BIN_PACKING_FITNESS_REF
    assert len(BIN_PACKING_FITNESS_REF.implementation_sha256) == 64


@pytest.mark.parametrize("goal,message", [
    (OptimisationGoal(MetricGoal("bins", "minimize"), "sum"), "bins_used"),
    (OptimisationGoal(MetricGoal("bins_used", "maximize"), "sum"), "bins_used"),
    (OptimisationGoal(MetricGoal("bins_used", "minimize"), "mean"), "bins_used"),
    (
        OptimisationGoal(
            MetricGoal("bins_used", "minimize"), "sum", (MetricGoal("slack", "minimize"),)
        ),
        "tie-breakers",
    ),
])
def test_validate_contract_rejects_a_mismatched_goal(goal, message):
    from dataclasses import replace

    with pytest.raises(ValueError, match=message):
        FITNESS.validate_contract(replace(bin_packing_contract(), optimisation_goal=goal))


def test_validate_contract_rejects_a_different_interface():
    problem = ProblemContract(
        natural_language_spec="placeholder",
        lean_specification="-- placeholder",
        interface=InterfaceDefinition(
            "python-interface-v1",
            (Parameter("n", "int"),),
            "list[int]",
            "def solve(n: int) -> list[int]:",
        ),
        seed_program="def solve(n: int) -> list[int]:\n    return [0] * n\n",
        evaluation_suite=EvaluationSuite("other", (EvaluationCase("n-2", {"n": 2}),)),
        optimisation_goal=OptimisationGoal(MetricGoal("bins_used", "minimize"), "sum"),
        resource_limits=ResourceLimits(1.0, 2.0, 64, 1),
        fitness_function=BIN_PACKING_FITNESS_REF,
    )
    with pytest.raises(ValueError, match=r"solve\(capacity"):
        FITNESS.validate_contract(problem)


@pytest.mark.parametrize("inputs,message", [
    ({"capacity": 0, "sizes": [1]}, "positive integer"),
    ({"capacity": 10, "sizes": []}, "between 1 and"),
    ({"capacity": 10, "sizes": [11]}, "between 1 and the capacity"),
    ({"capacity": 10, "sizes": [0]}, "between 1 and the capacity"),
])
def test_validate_contract_rejects_unusable_cases(inputs, message):
    from dataclasses import replace

    contract = bin_packing_contract()
    # The suite is validated structurally by ProblemContract, so the rejection under
    # test is the fitness function's own range check on an otherwise valid case.
    suite = EvaluationSuite("probe", (EvaluationCase("probe-1", inputs),))
    with pytest.raises(ValueError, match=message):
        FITNESS.validate_contract(replace(contract, evaluation_suite=suite))


def test_registry_resolves_the_bin_packing_function():
    from the_pigeon_holes.fitness.registry import builtin_registry

    resolved = builtin_registry().resolve(BIN_PACKING_FITNESS_REF)
    assert resolved.reference == BIN_PACKING_FITNESS_REF
