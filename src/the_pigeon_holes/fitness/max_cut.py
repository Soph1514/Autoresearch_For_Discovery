"""Exact max-cut validity and scoring.

Objective source: https://arxiv.org/abs/1711.02419
See docs/known-problems.md for the supported variant and qualification.
"""

from __future__ import annotations

from the_pigeon_holes.models.problem_contract import EvaluationCase, FitnessFunctionRef, ProblemContract
from .base import CaseFitness
from .registry import source_sha256

MAX_CUT_FITNESS_REF = FitnessFunctionRef("max-cut", "exact-v1", source_sha256(__file__))
MAX_VERTICES = 4096
MAX_EDGES = 65536
MAX_VALUE = 10**9


class MaxCutFitnessFunction:
    reference = MAX_CUT_FITNESS_REF

    def validate_contract(self, problem: ProblemContract) -> None:
        if problem.fitness_function != self.reference:
            raise ValueError("max-cut fitness reference does not match the contract")
        interface = problem.interface
        if ([(p.name, p.python_type) for p in interface.parameters]
                != [("n","int"),("edges","list[list[int]]")]
                or interface.return_type != "list[int]"
                or interface.supporting_types_code.strip()):
            raise ValueError("max-cut requires def solve(n: int, edges: list[list[int]]) -> list[int]: without supporting types")
        goal = problem.optimisation_goal
        if (goal.primary.name != "cut_weight" or goal.primary.direction != "maximize"
                or goal.aggregation != "sum" or goal.tie_breakers):
            raise ValueError("max-cut requires sum cut_weight maximize without tie-breakers")
        for case in problem.evaluation_suite.cases:
            inputs = case.materialize_inputs()
            n, edges = inputs["n"], inputs["edges"]
            if type(n) is not int or not 1 <= n <= MAX_VERTICES or len(edges) > MAX_EDGES:
                raise ValueError("max cut vertex/edge count exceeds supported bounds")
            seen = set()
            for edge in edges:
                if len(edge) != 3 or any(type(x) is not int for x in edge):
                    raise ValueError("max cut edges must be integer triples [u, v, weight]")
                u, v, weight = edge
                if not (0 <= u < n and 0 <= v < n and u != v and 0 <= weight <= MAX_VALUE):
                    raise ValueError("max cut requires distinct in-range endpoints and nonnegative bounded weights")
                key = (min(u, v), max(u, v))
                if key in seen:
                    raise ValueError("max cut requires unique undirected edges")
                seen.add(key)

    def evaluate_case(self, case: EvaluationCase, output: object) -> CaseFitness:
        inputs = case.materialize_inputs()
        n, edges = inputs["n"], inputs["edges"]
        if not isinstance(output, (list, tuple)) or len(output) != n:
            return CaseFitness(False, failure_reason="return one partition label per vertex")
        if any(type(side) is not int or side not in (0, 1) for side in output):
            return CaseFitness(False, failure_reason="partition labels must be integer 0 or 1")
        weight = sum(w for u, v, w in edges if output[u] != output[v])
        smaller_side = min(sum(output), n - sum(output))
        return CaseFitness(
            True, metrics={"cut_weight": weight},
            behavioral_descriptor=(float(8 * smaller_side // n),),
            evidence={"output": list(output), "cut_weight": weight},
        )
