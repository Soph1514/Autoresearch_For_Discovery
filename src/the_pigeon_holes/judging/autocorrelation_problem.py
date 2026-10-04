"""Problem contract for the first autocorrelation inequality (stage 0 family)."""

from __future__ import annotations

from the_pigeon_holes.execution.signature_extractor import MetricGoal, OptimisationGoal, Parameter
from the_pigeon_holes.judging.autocorrelation import JUDGE_VERSION, SCALE_BITS
from the_pigeon_holes.models.problem_contract import (
    EvaluationCase,
    EvaluationSuite,
    InterfaceDefinition,
    ProblemContract,
    ResourceLimits,
)

PROBLEM_TEXT = (
    "Construct a nonnegative step function f on [-1/4, 1/4] that makes the autoconvolution "
    "ratio C1(f) = max(f * f) / (integral of f)**2 as small as possible. Lower is better.\n\n"
    "Output convention (exact integer arithmetic): return a list of n nonnegative Python "
    f"integers q[0..n-1]. Cell i has value q[i] / 2**{SCALE_BITS}, so the function values "
    f"are multiples of 2**-{SCALE_BITS}. Values in plain units (for example 1 for the value "
    f"1.0) are invalid; write 2**{SCALE_BITS} for the value 1.0. The list must not be all "
    "zeros and its integral must not be too small. Floats are rejected."
)

SEED_SOURCE = (
    "def solve(n: int) -> list[int]:\n"
    f"    return [2**{SCALE_BITS}] * n\n"
)

LEAN_PLACEHOLDER = (
    "-- Formal statement pending review. The Python judge is checked against the "
    "natural-language statement and the property tests in tests/test_autocorrelation_judge.py."
)


def autocorrelation_contract(
    n: int = 600,
    *,
    case_time_seconds: float = 10.0,
    candidate_time_seconds: float = 20.0,
    memory_mb: int = 256,
) -> ProblemContract:
    """Build the fixed-instance contract: one case that fixes the output length n."""
    return ProblemContract(
        natural_language_spec=PROBLEM_TEXT,
        lean_specification=LEAN_PLACEHOLDER,
        interface=InterfaceDefinition(
            "python-interface-v1",
            (Parameter("n", "int"),),
            "list[int]",
            "def solve(n: int) -> list[int]:",
        ),
        seed_program=SEED_SOURCE,
        evaluation_suite=EvaluationSuite(
            f"autocorr-n{n}",
            (EvaluationCase(f"n-{n}", {"n": n}),),
        ),
        optimisation_goal=OptimisationGoal(MetricGoal("c1", "minimize"), "mean"),
        resource_limits=ResourceLimits(
            case_time_seconds=case_time_seconds,
            candidate_time_seconds=candidate_time_seconds,
            memory_mb=memory_mb,
            max_iterations=1,
        ),
        evaluator_version=JUDGE_VERSION,
    )
