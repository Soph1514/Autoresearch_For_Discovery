"""Exact tsp validity and scoring.

Objective source: https://developers.google.com/optimization/routing/tsp
See docs/known-problems.md for the supported variant and qualification.
"""

from __future__ import annotations

from the_pigeon_holes.models.problem_contract import EvaluationCase, FitnessFunctionRef, ProblemContract
from .base import CaseFitness
from .registry import source_sha256

TSP_FITNESS_REF = FitnessFunctionRef("tsp", "exact-v1", source_sha256(__file__))
MAX_CITIES = 256
MAX_VALUE = 10**9


class TspFitnessFunction:
    reference = TSP_FITNESS_REF

    def validate_contract(self, problem: ProblemContract) -> None:
        if problem.fitness_function != self.reference:
            raise ValueError("tsp fitness reference does not match the contract")
        interface = problem.interface
        if ([(p.name, p.python_type) for p in interface.parameters]
                != [("distances","list[list[int]]")]
                or interface.return_type != "list[int]"
                or interface.supporting_types_code.strip()):
            raise ValueError("tsp requires def solve(distances: list[list[int]]) -> list[int]: without supporting types")
        goal = problem.optimisation_goal
        if (goal.primary.name != "tour_length" or goal.primary.direction != "minimize"
                or goal.aggregation != "sum" or goal.tie_breakers):
            raise ValueError("tsp requires sum tour_length minimize without tie-breakers")
        for case in problem.evaluation_suite.cases:
            inputs = case.materialize_inputs()
            distances = inputs["distances"]
            n = len(distances)
            if not 2 <= n <= MAX_CITIES or any(len(row) != n for row in distances):
                raise ValueError("TSP requires a square matrix of 2 to 256 cities")
            if any(type(x) is not int or not 0 <= x <= MAX_VALUE for row in distances for x in row):
                raise ValueError("TSP distances must be nonnegative bounded integers")
            if any(distances[i][i] != 0 for i in range(n)):
                raise ValueError("TSP diagonal distances must be zero")
            if any(distances[i][j] != distances[j][i] for i in range(n) for j in range(i)):
                raise ValueError("this TSP fitness function requires symmetric distances")

    def evaluate_case(self, case: EvaluationCase, output: object) -> CaseFitness:
        inputs = case.materialize_inputs()
        distances = inputs["distances"]
        n = len(distances)
        if not isinstance(output, (list, tuple)) or len(output) != n:
            return CaseFitness(False, failure_reason="return exactly one entry per city, without repeating the start")
        if any(type(i) is not int or not 0 <= i < n for i in output) or len(set(output)) != n:
            return CaseFitness(False, failure_reason="tour must be a permutation of all city indices")
        edges = [distances[output[i]][output[(i + 1) % n]] for i in range(n)]
        length = sum(edges)
        return CaseFitness(
            True, metrics={"tour_length": length},
            behavioral_descriptor=(float(min(3, 4 * max(edges) // max(1, length))),),
            evidence={"output": list(output), "edge_lengths": edges, "tour_length": length},
        )
