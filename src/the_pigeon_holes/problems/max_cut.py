"""Built-in max-cut construction instances and baseline."""

from the_pigeon_holes.fitness.max_cut import MAX_CUT_FITNESS_REF
from the_pigeon_holes.models.problem_contract import (
    EvaluationCase, EvaluationSuite, InterfaceDefinition, MetricGoal,
    OptimisationGoal, Parameter, ProblemContract, ResourceLimits,
)
from .specs import load_instances, load_problem_text

PROBLEM_NAME = "max-cut"
INSTANCES = load_instances(PROBLEM_NAME)
# Reporting only: neither targets nor witnesses enter the contract or prompts.
BEST_KNOWN = {row["id"]: row["target"] for row in INSTANCES}

SEED_SOURCE = """def solve(n: int, edges: list[list[int]]) -> list[int]:
    sides = [0] * n
    for v in range(n):
        gains = [0, 0]
        for a, b, weight in edges:
            other = b if a == v else a if b == v else -1
            if 0 <= other < v:
                gains[1 - sides[other]] += weight
        sides[v] = 1 if gains[1] > gains[0] else 0
    return sides
"""


def max_cut_contract(*, case_time_seconds: float = 5.0,
                      candidate_time_seconds: float = 30.0,
                      memory_mb: int = 256) -> ProblemContract:
    return ProblemContract(
        natural_language_spec=load_problem_text(PROBLEM_NAME),
        lean_specification="-- Formal statement pending formalization and review.",
        interface=InterfaceDefinition(
            "python-interface-v1",
            (Parameter("n", "int"), Parameter("edges", "list[list[int]]"),),
            "list[int]",
            "def solve(n: int, edges: list[list[int]]) -> list[int]:",
        ),
        seed_program=SEED_SOURCE,
        evaluation_suite=EvaluationSuite(
            "max-cut-examples-v1",
            tuple(EvaluationCase(row["id"], row["inputs"]) for row in INSTANCES),
        ),
        optimisation_goal=OptimisationGoal(MetricGoal("cut_weight", "maximize"), "sum"),
        resource_limits=ResourceLimits(case_time_seconds, candidate_time_seconds, memory_mb, 1),
        fitness_function=MAX_CUT_FITNESS_REF,
    )
