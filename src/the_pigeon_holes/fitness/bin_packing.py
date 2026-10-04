"""Exact fitness function for bin packing with a fixed capacity.

A candidate returns one bin index per item. Validity and the objective are
decided with integer arithmetic only: a bin's load is a sum of item sizes, and
``bins_used`` counts the distinct indices that hold at least one item, so
relabelling bins cannot change the score.
"""

from __future__ import annotations

from typing import Sequence

from the_pigeon_holes.models.problem_contract import (
    EvaluationCase,
    FitnessFunctionRef,
    ProblemContract,
)

from .base import CaseFitness
from .registry import source_sha256

FITNESS_FUNCTION_ID = "bin-packing"
FITNESS_FUNCTION_VERSION = "exact-v1"
BIN_PACKING_FITNESS_REF = FitnessFunctionRef(
    id=FITNESS_FUNCTION_ID,
    version=FITNESS_FUNCTION_VERSION,
    implementation_sha256=source_sha256(__file__),
)

MAX_ITEMS = 4096
FILL_BINS = 4
EXCESS_CAP = 8


class InvalidOutput(ValueError):
    """The candidate assignment breaks a rule of this problem family."""


def bin_loads(assignment: Sequence[int], sizes: Sequence[int]) -> dict[int, int]:
    """Return the total size assigned to each used bin index."""
    loads: dict[int, int] = {}
    for position, bin_index in enumerate(assignment):
        loads[bin_index] = loads.get(bin_index, 0) + sizes[position]
    return loads


def validate_assignment(
    assignment: object, capacity: int, sizes: Sequence[int]
) -> list[int]:
    """Return the assignment as a list of ints, or raise ``InvalidOutput``.

    Failure reasons never quote capacity or item sizes, because they are returned
    to generation as repair feedback.
    """
    if not isinstance(assignment, (list, tuple)):
        raise InvalidOutput("output must be a list or tuple of bin indices")
    if len(assignment) != len(sizes):
        raise InvalidOutput(
            f"expected one bin index per item: {len(sizes)} entries, got {len(assignment)}"
        )
    for position, bin_index in enumerate(assignment):
        if type(bin_index) is not int:
            raise InvalidOutput(f"non-integer bin index at position {position}")
        if bin_index < 0:
            raise InvalidOutput(f"negative bin index at position {position}")
    overfull = sum(
        1 for load in bin_loads(assignment, sizes).values() if load > capacity
    )
    if overfull:
        raise InvalidOutput(f"{overfull} bin(s) hold more than the capacity")
    return list(assignment)


def lower_bound(capacity: int, sizes: Sequence[int]) -> int:
    """Return the volume bound ``ceil(sum(sizes) / capacity)`` on the bin count."""
    return -(-sum(sizes) // capacity)


def bins_used(assignment: object, capacity: int, sizes: Sequence[int]) -> int:
    """Return the number of occupied bins for a feasible assignment."""
    return len(set(validate_assignment(assignment, capacity, sizes)))


def descriptor_cell(
    assignment: object, capacity: int, sizes: Sequence[int]
) -> tuple[int, int]:
    """Describe mechanism: bins above the volume bound, and how full bins run.

    Both parts are bounded, so the number of behavioural cells stays small. The
    first part is never negative because a feasible assignment cannot use fewer
    bins than the volume bound.
    """
    valid = validate_assignment(assignment, capacity, sizes)
    loads = bin_loads(valid, sizes)
    excess = min(len(loads) - lower_bound(capacity, sizes), EXCESS_CAP)
    mean_fill = sum(loads.values()) / (len(loads) * capacity)
    return (excess, min(int(mean_fill * FILL_BINS), FILL_BINS - 1))


class BinPackingFitnessFunction:
    """Validate bin assignments and count the bins they occupy."""

    reference = BIN_PACKING_FITNESS_REF

    def validate_contract(self, problem: ProblemContract) -> None:
        if problem.fitness_function != self.reference:
            raise ValueError("bin packing fitness reference does not match the contract")
        interface = problem.interface
        if (
            [(parameter.name, parameter.python_type) for parameter in interface.parameters]
            != [("capacity", "int"), ("sizes", "list[int]")]
            or interface.return_type != "list[int]"
            or interface.supporting_types_code.strip()
        ):
            raise ValueError(
                "bin packing requires solve(capacity: int, sizes: list[int]) -> list[int] "
                "without supporting types"
            )
        goal = problem.optimisation_goal
        if (
            goal.primary.name != "bins_used"
            or goal.primary.direction != "minimize"
            or goal.aggregation != "sum"
            or goal.tie_breakers
        ):
            raise ValueError(
                "bin packing requires sum bins_used minimization without tie-breakers"
            )
        for case in problem.evaluation_suite.cases:
            capacity = case.inputs.get("capacity")
            sizes = case.inputs.get("sizes")
            if type(capacity) is not int or capacity <= 0:
                raise ValueError("bin packing case capacity must be a positive integer")
            if sizes is None or not 1 <= len(sizes) <= MAX_ITEMS:
                raise ValueError(
                    f"bin packing case must hold between 1 and {MAX_ITEMS} items"
                )
            if any(type(size) is not int or not 1 <= size <= capacity for size in sizes):
                raise ValueError(
                    "bin packing item sizes must be integers between 1 and the capacity"
                )

    def evaluate_case(self, case: EvaluationCase, output: object) -> CaseFitness:
        inputs = case.materialize_inputs()
        capacity, sizes = inputs["capacity"], inputs["sizes"]
        try:
            assignment = validate_assignment(output, capacity, sizes)
        except InvalidOutput as error:
            return CaseFitness(valid=False, failure_reason=str(error))
        used = len(set(assignment))
        return CaseFitness(
            valid=True,
            metrics={"bins_used": used},
            behavioral_descriptor=tuple(
                float(part) for part in descriptor_cell(assignment, capacity, sizes)
            ),
            evidence={
                # "output" is the shared key every fitness function records the
                # candidate's result under, so generic tooling can recheck it.
                "output": assignment,
                "bins_used_exact": {"numerator": str(used), "denominator": "1"},
                "lower_bound": lower_bound(capacity, sizes),
            },
        )
