"""Problem contract for bin packing on instances with a provable optimum.

Items are generated in triples that each sum to exactly the capacity, so a
packing into one bin per triple exists and the volume bound
``ceil(sum(sizes) / capacity)`` equals the number of triples. The optimum is
therefore known by construction rather than quoted from a benchmark table, and
``tests/test_bin_packing_fitness.py`` re-derives it instead of trusting
``BEST_KNOWN``. This is the Falkenauer triplet family, which is standard because
first-fit-decreasing overshoots it.
"""

from __future__ import annotations

import random

from the_pigeon_holes.execution.signature_extractor import (
    MetricGoal,
    OptimisationGoal,
    Parameter,
)
from the_pigeon_holes.fitness.bin_packing import BIN_PACKING_FITNESS_REF
from the_pigeon_holes.models.problem_contract import (
    EvaluationCase,
    EvaluationSuite,
    InterfaceDefinition,
    ProblemContract,
    ResourceLimits,
)

from .specs import load_problem_text

PROBLEM_NAME = "bin-packing"
CAPACITY = 1000

# (case id, number of triples, generator seed). Each case's optimum is its triple
# count. Seeds were chosen so first-fit-decreasing is strictly worse on every case,
# which is what leaves the search something to improve.
INSTANCES = (
    ("triplet-10", 10, 0),
    ("triplet-20", 20, 1),
    ("triplet-30", 30, 4),
)

BEST_KNOWN = {
    case_id: {
        "value": triples,
        "kind": "optimal",
        "justification": (
            "Item sizes form disjoint triples each summing to the capacity, so one bin "
            "per triple is feasible, and ceil(sum(sizes) / capacity) equals the triple "
            "count, so no assignment uses fewer bins."
        ),
    }
    for case_id, triples, _ in INSTANCES
}

SEED_SOURCE = """def solve(capacity: int, sizes: list[int]) -> list[int]:
    order = sorted(range(len(sizes)), key=lambda item: -sizes[item])
    assignment = [0] * len(sizes)
    loads: list[int] = []
    for item in order:
        for index, load in enumerate(loads):
            if load + sizes[item] <= capacity:
                loads[index] = load + sizes[item]
                assignment[item] = index
                break
        else:
            assignment[item] = len(loads)
            loads.append(sizes[item])
    return assignment
"""

LEAN_PLACEHOLDER = (
    "-- Formal statement pending formalization. The Python fitness function is checked "
    "against the natural-language statement and its property tests."
)


def _triple(rng: random.Random, capacity: int) -> tuple[int, int, int]:
    """Draw three strictly decreasing sizes summing to exactly the capacity."""
    first = rng.randint(capacity * 38 // 100, capacity * 49 // 100)
    remaining = capacity - first
    second = rng.randint(remaining // 2 + 1, min(remaining - 1, first - 1))
    return (first, second, remaining - second)


def triplet_groups(
    triples: int, capacity: int = CAPACITY, seed: int = 0
) -> list[tuple[int, int, int]]:
    """Return the triples the instance is built from, before they are shuffled.

    This is the construction the optimum rests on: each triple sums to exactly
    the capacity, so one bin per triple is feasible. The tests use it to rebuild a
    provably optimal packing rather than searching for one.
    """
    rng = random.Random(seed)
    return [_triple(rng, capacity) for _ in range(triples)]


def triplet_sizes(triples: int, capacity: int = CAPACITY, seed: int = 0) -> list[int]:
    """Flatten the triples into the shuffled item list a candidate receives.

    Shuffling hides the grouping; the size spread within a triple is what makes
    the instance awkward for greedy packing.
    """
    rng = random.Random(seed)
    groups = [_triple(rng, capacity) for _ in range(triples)]
    sizes = [size for group in groups for size in group]
    rng.shuffle(sizes)
    return sizes


def optimal_assignment(
    triples: int, capacity: int = CAPACITY, seed: int = 0
) -> list[int]:
    """Exhibit a packing attaining the optimum for the matching ``triplet_sizes``.

    Giving each triple its own bin uses exactly ``triples`` bins, which is the
    volume bound. Stating an optimum is only meaningful if one can be produced, so
    this keeps ``BEST_KNOWN`` checkable rather than asserted. Like ``BEST_KNOWN``
    it is reporting and test data: it is unreachable from the fitness function, the
    contract and every generation prompt.
    """
    sizes = triplet_sizes(triples, capacity, seed)
    positions: dict[int, list[int]] = {}
    for index, size in enumerate(sizes):
        positions.setdefault(size, []).append(index)
    assignment = [0] * len(sizes)
    for bin_index, group in enumerate(triplet_groups(triples, capacity, seed)):
        for size in group:
            assignment[positions[size].pop()] = bin_index
    return assignment


def bin_packing_contract(
    *,
    case_time_seconds: float = 5.0,
    candidate_time_seconds: float = 30.0,
    memory_mb: int = 256,
) -> ProblemContract:
    """Build the frozen contract over the fixed triplet suite."""
    return ProblemContract(
        natural_language_spec=load_problem_text(PROBLEM_NAME),
        lean_specification=LEAN_PLACEHOLDER,
        interface=InterfaceDefinition(
            "python-interface-v1",
            (Parameter("capacity", "int"), Parameter("sizes", "list[int]")),
            "list[int]",
            "def solve(capacity: int, sizes: list[int]) -> list[int]:",
        ),
        seed_program=SEED_SOURCE,
        evaluation_suite=EvaluationSuite(
            "bin-packing-triplets-v1",
            tuple(
                EvaluationCase(
                    case_id,
                    {"capacity": CAPACITY, "sizes": triplet_sizes(triples, seed=seed)},
                )
                for case_id, triples, seed in INSTANCES
            ),
        ),
        optimisation_goal=OptimisationGoal(MetricGoal("bins_used", "minimize"), "sum"),
        resource_limits=ResourceLimits(
            case_time_seconds=case_time_seconds,
            candidate_time_seconds=candidate_time_seconds,
            memory_mb=memory_mb,
            max_iterations=1,
        ),
        fitness_function=BIN_PACKING_FITNESS_REF,
    )
