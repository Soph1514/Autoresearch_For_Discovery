"""Built-in tsp construction instances and baseline."""

from problems.tsp.fitness import TSP_FITNESS_REF
from the_pigeon_holes.models.problem_contract import (
    EvaluationCase, EvaluationSuite, InterfaceDefinition, MetricGoal,
    OptimisationGoal, Parameter, ProblemContract, ResourceLimits,
)
from .specs import load_instances, load_problem_text

PROBLEM_NAME = "tsp"
INSTANCES = load_instances(PROBLEM_NAME)
# Reporting only: neither targets nor witnesses enter the contract or prompts.
BEST_KNOWN = {row["id"]: row["target"] for row in INSTANCES}

SEED_SOURCE = """def solve(distances: list[list[int]]) -> list[int]:
    tour = [0]
    remaining = set(range(1, len(distances)))
    while remaining:
        city = min(remaining, key=lambda i: (distances[tour[-1]][i], i))
        tour.append(city)
        remaining.remove(city)
    return tour
"""


def tsp_contract(*, case_time_seconds: float = 5.0,
                      candidate_time_seconds: float = 30.0,
                      memory_mb: int = 256) -> ProblemContract:
    return ProblemContract(
        natural_language_spec=load_problem_text(PROBLEM_NAME),
        lean_specification="-- Formal statement pending formalization and review.",
        interface=InterfaceDefinition(
            "python-interface-v1",
            (Parameter("distances", "list[list[int]]"),),
            "list[int]",
            "def solve(distances: list[list[int]]) -> list[int]:",
        ),
        seed_program=SEED_SOURCE,
        evaluation_suite=EvaluationSuite(
            "tsp-examples-v1",
            tuple(EvaluationCase(row["id"], row["inputs"]) for row in INSTANCES),
        ),
        optimisation_goal=OptimisationGoal(MetricGoal("tour_length", "minimize"), "sum"),
        resource_limits=ResourceLimits(case_time_seconds, candidate_time_seconds, memory_mb, 1),
        fitness_function=TSP_FITNESS_REF,
    )
