"""Exact knapsack validity and scoring.

Objective source: https://developers.google.com/optimization/pack/knapsack
See docs/known-problems.md for the supported variant and qualification.
"""

from __future__ import annotations

from the_pigeon_holes.models.problem_contract import EvaluationCase, FitnessFunctionRef, ProblemContract
from the_pigeon_holes.fitness.base import CaseFitness
from the_pigeon_holes.fitness.registry import source_sha256

KNAPSACK_FITNESS_REF = FitnessFunctionRef("knapsack", "exact-v1", source_sha256(__file__))
MAX_ITEMS = 4096
MAX_VALUE = 10**9


class KnapsackFitnessFunction:
    reference = KNAPSACK_FITNESS_REF

    def validate_contract(self, problem: ProblemContract) -> None:
        if problem.fitness_function != self.reference:
            raise ValueError("knapsack fitness reference does not match the contract")
        interface = problem.interface
        if ([(p.name, p.python_type) for p in interface.parameters]
                != [("capacity","int"),("weights","list[int]"),("values","list[int]")]
                or interface.return_type != "list[int]"
                or interface.supporting_types_code.strip()):
            raise ValueError("knapsack requires def solve(capacity: int, weights: list[int], values: list[int]) -> list[int]: without supporting types")
        goal = problem.optimisation_goal
        if (goal.primary.name != "total_value" or goal.primary.direction != "maximize"
                or goal.aggregation != "sum" or goal.tie_breakers):
            raise ValueError("knapsack requires sum total_value maximize without tie-breakers")
        for case in problem.evaluation_suite.cases:
            inputs = case.materialize_inputs()
            capacity, weights, values = (inputs[key] for key in ("capacity", "weights", "values"))
            if type(capacity) is not int or not 0 <= capacity <= MAX_VALUE:
                raise ValueError("knapsack capacity must be a nonnegative bounded integer")
            if not 1 <= len(weights) <= MAX_ITEMS or len(weights) != len(values):
                raise ValueError("knapsack requires matching nonempty weight/value lists")
            if any(type(x) is not int or not 0 <= x <= MAX_VALUE for x in (*weights, *values)):
                raise ValueError("knapsack weights and values must be nonnegative bounded integers")

    def evaluate_case(self, case: EvaluationCase, output: object) -> CaseFitness:
        inputs = case.materialize_inputs()
        weights, values, capacity = (inputs[key] for key in ("weights", "values", "capacity"))
        if not isinstance(output, (list, tuple)) or len(output) > len(weights):
            return CaseFitness(False, failure_reason="return a list of selected item indices")
        if any(type(i) is not int or not 0 <= i < len(weights) for i in output):
            return CaseFitness(False, failure_reason="selected item indices must be in-range integers")
        if len(set(output)) != len(output):
            return CaseFitness(False, failure_reason="each item may be selected at most once")
        weight = sum(weights[i] for i in output)
        if weight > capacity:
            return CaseFitness(False, failure_reason="selected items exceed capacity")
        value = sum(values[i] for i in output)
        return CaseFitness(
            True, metrics={"total_value": value},
            behavioral_descriptor=(float(min(3, 4 * weight // max(1, capacity))),
                                   float(min(3, 4 * len(output) // len(weights)))),
            evidence={"output": list(output), "total_weight": weight, "total_value": value},
        )
