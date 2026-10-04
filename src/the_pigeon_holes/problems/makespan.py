"""Built-in makespan construction instances and baseline."""

from the_pigeon_holes.fitness.makespan import MAKESPAN_FITNESS_REF
from the_pigeon_holes.models.problem_contract import (
    EvaluationCase, EvaluationSuite, InterfaceDefinition, MetricGoal,
    OptimisationGoal, Parameter, ProblemContract, ResourceLimits,
)
from .specs import load_instances, load_problem_text

PROBLEM_NAME = "makespan"
INSTANCES = load_instances(PROBLEM_NAME)
# Reporting only: neither targets nor witnesses enter the contract or prompts.
BEST_KNOWN = {row["id"]: row["target"] for row in INSTANCES}

SEED_SOURCE = """def solve(machines: int, durations: list[int]) -> list[int]:
    loads = [0] * machines
    assignment = [0] * len(durations)
    for job in sorted(range(len(durations)), key=lambda j: -durations[j]):
        machine = min(range(machines), key=lambda i: loads[i])
        assignment[job] = machine
        loads[machine] += durations[job]
    return assignment
"""


def makespan_contract(*, case_time_seconds: float = 5.0,
                      candidate_time_seconds: float = 30.0,
                      memory_mb: int = 256) -> ProblemContract:
    return ProblemContract(
        natural_language_spec=load_problem_text(PROBLEM_NAME),
        lean_specification="-- Formal statement pending formalization and review.",
        interface=InterfaceDefinition(
            "python-interface-v1",
            (Parameter("machines", "int"), Parameter("durations", "list[int]"),),
            "list[int]",
            "def solve(machines: int, durations: list[int]) -> list[int]:",
        ),
        seed_program=SEED_SOURCE,
        evaluation_suite=EvaluationSuite(
            "makespan-examples-v1",
            tuple(EvaluationCase(row["id"], row["inputs"]) for row in INSTANCES),
        ),
        optimisation_goal=OptimisationGoal(MetricGoal("makespan", "minimize"), "sum"),
        resource_limits=ResourceLimits(case_time_seconds, candidate_time_seconds, memory_mb, 1),
        fitness_function=MAKESPAN_FITNESS_REF,
    )
