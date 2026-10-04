"""Built-in knapsack construction instances and baseline."""

from the_pigeon_holes.fitness.knapsack import KNAPSACK_FITNESS_REF
from the_pigeon_holes.models.problem_contract import (
    EvaluationCase, EvaluationSuite, InterfaceDefinition, MetricGoal,
    OptimisationGoal, Parameter, ProblemContract, ResourceLimits,
)
from .specs import load_instances, load_problem_text

PROBLEM_NAME = "knapsack"
INSTANCES = load_instances(PROBLEM_NAME)
# Reporting only: neither targets nor witnesses enter the contract or prompts.
BEST_KNOWN = {row["id"]: row["target"] for row in INSTANCES}

SEED_SOURCE = """def solve(capacity: int, weights: list[int], values: list[int]) -> list[int]:
    from fractions import Fraction
    order = sorted(range(len(weights)),
                   key=lambda i: (weights[i] == 0, Fraction(values[i], max(1, weights[i]))),
                   reverse=True)
    selected = []
    remaining = capacity
    for i in order:
        if weights[i] <= remaining:
            selected.append(i)
            remaining -= weights[i]
    return selected
"""


def knapsack_contract(*, case_time_seconds: float = 5.0,
                      candidate_time_seconds: float = 30.0,
                      memory_mb: int = 256) -> ProblemContract:
    return ProblemContract(
        natural_language_spec=load_problem_text(PROBLEM_NAME),
        lean_specification="-- Formal statement pending formalization and review.",
        interface=InterfaceDefinition(
            "python-interface-v1",
            (Parameter("capacity", "int"), Parameter("weights", "list[int]"), Parameter("values", "list[int]"),),
            "list[int]",
            "def solve(capacity: int, weights: list[int], values: list[int]) -> list[int]:",
        ),
        seed_program=SEED_SOURCE,
        evaluation_suite=EvaluationSuite(
            "knapsack-examples-v1",
            tuple(EvaluationCase(row["id"], row["inputs"]) for row in INSTANCES),
        ),
        optimisation_goal=OptimisationGoal(MetricGoal("total_value", "maximize"), "sum"),
        resource_limits=ResourceLimits(case_time_seconds, candidate_time_seconds, memory_mb, 1),
        fitness_function=KNAPSACK_FITNESS_REF,
    )
