"""Exact makespan validity and scoring.

Objective source: https://arxiv.org/abs/1304.5625
See docs/known-problems.md for the supported variant and qualification.
"""

from __future__ import annotations

from the_pigeon_holes.models.problem_contract import EvaluationCase, FitnessFunctionRef, ProblemContract
from .base import CaseFitness
from .registry import source_sha256

MAKESPAN_FITNESS_REF = FitnessFunctionRef("makespan", "exact-v1", source_sha256(__file__))
MAX_JOBS = 4096
MAX_MACHINES = 256
MAX_VALUE = 10**9


class MakespanFitnessFunction:
    reference = MAKESPAN_FITNESS_REF

    def validate_contract(self, problem: ProblemContract) -> None:
        if problem.fitness_function != self.reference:
            raise ValueError("makespan fitness reference does not match the contract")
        interface = problem.interface
        if ([(p.name, p.python_type) for p in interface.parameters]
                != [("machines","int"),("durations","list[int]")]
                or interface.return_type != "list[int]"
                or interface.supporting_types_code.strip()):
            raise ValueError("makespan requires def solve(machines: int, durations: list[int]) -> list[int]: without supporting types")
        goal = problem.optimisation_goal
        if (goal.primary.name != "makespan" or goal.primary.direction != "minimize"
                or goal.aggregation != "sum" or goal.tie_breakers):
            raise ValueError("makespan requires sum makespan minimize without tie-breakers")
        for case in problem.evaluation_suite.cases:
            inputs = case.materialize_inputs()
            machines, durations = inputs["machines"], inputs["durations"]
            if type(machines) is not int or not 1 <= machines <= MAX_MACHINES:
                raise ValueError("makespan machine count must be between 1 and 256")
            if not 1 <= len(durations) <= MAX_JOBS:
                raise ValueError("makespan requires a nonempty bounded job list")
            if any(type(x) is not int or not 1 <= x <= MAX_VALUE for x in durations):
                raise ValueError("makespan durations must be positive bounded integers")

    def evaluate_case(self, case: EvaluationCase, output: object) -> CaseFitness:
        inputs = case.materialize_inputs()
        machines, durations = inputs["machines"], inputs["durations"]
        if not isinstance(output, (list, tuple)) or len(output) != len(durations):
            return CaseFitness(False, failure_reason="return exactly one machine index per job")
        if any(type(i) is not int or not 0 <= i < machines for i in output):
            return CaseFitness(False, failure_reason="machine indices must be in-range integers")
        loads = [0] * machines
        for machine, duration in zip(output, durations):
            loads[machine] += duration
        makespan = max(loads)
        return CaseFitness(
            True, metrics={"makespan": makespan},
            behavioral_descriptor=(float(min(3, 4 * (makespan - min(loads)) // makespan)),),
            evidence={"output": list(output), "machine_loads": loads, "makespan": makespan},
        )
