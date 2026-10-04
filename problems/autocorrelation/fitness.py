"""Exact fitness function for the first autocorrelation inequality."""

from __future__ import annotations

from fractions import Fraction
from typing import Sequence

from the_pigeon_holes.models.problem_contract import (
    EvaluationCase,
    FitnessFunctionRef,
    ProblemContract,
)

from the_pigeon_holes.fitness.base import CaseFitness
from the_pigeon_holes.fitness.registry import source_sha256

FITNESS_FUNCTION_ID = "autocorrelation"
FITNESS_FUNCTION_VERSION = "exact-v1"
AUTOCORRELATION_FITNESS_REF = FitnessFunctionRef(
    id=FITNESS_FUNCTION_ID,
    version=FITNESS_FUNCTION_VERSION,
    implementation_sha256=source_sha256(__file__),
)

SCALE_BITS = 40
SCALE = 1 << SCALE_BITS
MIN_POINTS = 2
MAX_POINTS = 4096
MIN_INTEGRAL_SQUARED = Fraction(1, 10**8)
PUBLISHED_UPPER_BOUND = Fraction(1.5052939684401607)


class InvalidOutput(ValueError):
    """The candidate output breaks a rule of this problem family."""


def validate_output(values: object) -> list[int]:
    if not isinstance(values, (list, tuple)):
        raise InvalidOutput("output must be a list or tuple of integers")
    n = len(values)
    if not MIN_POINTS <= n <= MAX_POINTS:
        raise InvalidOutput(f"length {n} outside [{MIN_POINTS}, {MAX_POINTS}]")
    for index, value in enumerate(values):
        if type(value) is not int:
            raise InvalidOutput(f"non-integer value at index {index}")
        if value < 0:
            raise InvalidOutput(f"negative value at index {index}")
    total = sum(values)
    if total == 0:
        raise InvalidOutput("integral is zero")
    integral = Fraction(total, SCALE) / (2 * n)
    if integral * integral < MIN_INTEGRAL_SQUARED:
        raise InvalidOutput("integral is too small")
    return list(values)


def max_autoconvolution(values: Sequence[int]) -> int:
    n = len(values)
    best = 0
    for k in range(2 * n - 1):
        low = max(0, k - n + 1)
        high = min(k, n - 1)
        total = sum(values[i] * values[k - i] for i in range(low, high + 1))
        best = max(best, total)
    return best


def c1(values: object) -> Fraction:
    q = validate_output(values)
    n = len(q)
    total = sum(q)
    return Fraction(2 * n * max_autoconvolution(q), total * total)


def beats_published_bound(values: object) -> bool:
    return c1(values) < PUBLISHED_UPPER_BOUND


def support_fraction(values: object) -> float:
    q = validate_output(values)
    return sum(1 for value in q if value) / len(q)


def autoconvolution_peaks(values: object) -> int:
    q = validate_output(values)
    n = len(q)
    conv = [
        sum(q[i] * q[k - i] for i in range(max(0, k - n + 1), min(k, n - 1) + 1))
        for k in range(2 * n - 1)
    ]
    return sum(
        1
        for k in range(1, len(conv) - 1)
        if conv[k] > conv[k - 1] and conv[k] > conv[k + 1]
    )


SUPPORT_BINS = 4
PEAK_CAP = 8


def descriptor_cell(values: object) -> tuple[int, int]:
    support = support_fraction(values)
    return (
        min(int(support * SUPPORT_BINS), SUPPORT_BINS - 1),
        min(autoconvolution_peaks(values), PEAK_CAP),
    )


class AutocorrelationFitnessFunction:
    """Validate autocorrelation witnesses and compute exact objective values."""

    reference = AUTOCORRELATION_FITNESS_REF

    def validate_contract(self, problem: ProblemContract) -> None:
        if problem.fitness_function != self.reference:
            raise ValueError("autocorrelation fitness reference does not match the contract")
        interface = problem.interface
        if (
            [(parameter.name, parameter.python_type) for parameter in interface.parameters]
            != [("n", "int")]
            or interface.return_type != "list[int]"
            or interface.supporting_types_code.strip()
        ):
            raise ValueError(
                "autocorrelation requires solve(n: int) -> list[int] without supporting types"
            )
        goal = problem.optimisation_goal
        if (
            goal.primary.name != "c1"
            or goal.primary.direction != "minimize"
            or goal.aggregation != "mean"
            or goal.tie_breakers
        ):
            raise ValueError(
                "autocorrelation requires mean c1 minimization without tie-breakers"
            )
        for case in problem.evaluation_suite.cases:
            n = case.inputs.get("n")
            if type(n) is not int or not MIN_POINTS <= n <= MAX_POINTS:
                raise ValueError(
                    f"autocorrelation case n must be between {MIN_POINTS} and {MAX_POINTS}"
                )

    def evaluate_case(self, case: EvaluationCase, output: object) -> CaseFitness:
        try:
            values = validate_output(output)
            expected = case.inputs["n"]
            if len(values) != expected:
                raise InvalidOutput(f"expected length {expected}, got {len(values)}")
            value = c1(values)
            return CaseFitness(
                valid=True,
                metrics={"c1": value},
                behavioral_descriptor=tuple(float(part) for part in descriptor_cell(values)),
                evidence={
                    "output": values,
                    "c1_exact": {
                        "numerator": str(value.numerator),
                        "denominator": str(value.denominator),
                    },
                },
            )
        except InvalidOutput as error:
            return CaseFitness(valid=False, failure_reason=str(error))
