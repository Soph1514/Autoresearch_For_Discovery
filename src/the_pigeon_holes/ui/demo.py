"""Explicit demo ports: deterministic proposals and analytic Pigou evaluation.

No generated Python is executed. These adapters are not a general evaluator,
LLM generator, sandbox, or Lean verifier.
"""
import ast
import asyncio
from the_pigeon_holes.models.problem_contract import (
    ProblemContract, ResourceLimits, OptimisationGoal, MetricGoal,
)
from the_pigeon_holes.evolution.models import (
    CandidateDraft, GenerationResult, TokenUsage, CandidateEvaluation,
)


def demo_contract():
    return ProblemContract(
        natural_language_spec="Maximize the PoA witness for unit-demand Pigou routing: delays x and c, 0 < c <= 1.",
        lean_specification="-- Demo placeholder: no Lean proof has been checked.",
        solve_signature="def solve() -> float:", seed_program="def solve() -> float:\n    return 0.3\n",
        instance_id="pigou-unit-demand", instance={},
        optimisation_goal=OptimisationGoal(MetricGoal("poa", "maximize"), "mean"),
        resource_limits=ResourceLimits(2, 128, 20), evaluator_version="pigou-analytic-demo-v1",
    )


class DemoGenerator:
    def __init__(self, checkpoint, log, delay=0.8):
        self.checkpoint, self.log, self.delay = checkpoint, log, delay
        self.number = 0

    async def generate(self, requests):
        await self.checkpoint()
        self.log("generate", f"Generation {requests[0].generation}: {len(requests)} requests across search islands.")
        await asyncio.sleep(self.delay)
        results = []
        for request in requests:
            self.number += 1
            c = round(min(1.0, .3 + .05 * self.number), 2)
            # A distinct but invalid proposal exercises failure handling.
            if self.number == 4:
                c = 1.2
            results.append(GenerationResult(
                request_id=request.id, usage=TokenUsage(4, 6),
                draft=CandidateDraft(
                    hypothesis=f"Test constant-route delay c = {c:g}",
                    predicted_effect="Increase the verified equilibrium / optimum cost ratio.",
                    falsification_condition="The witness is infeasible or does not improve the ratio.",
                    mechanism_tags=("pigou", request.operator.value),
                    source_code=f"def solve() -> float:\n    return {c}\n",
                ),
            ))
        return tuple(results)


class DemoEvaluator:
    def __init__(self, publish_candidate, publish_evaluation, delay=.8):
        self.publish_candidate, self.publish_evaluation = publish_candidate, publish_evaluation
        self.delay = delay

    async def evaluate(self, candidates, problem):
        async def evaluate_one(candidate):
            self.publish_candidate(candidate)
            await asyncio.sleep(self.delay)
            try:
                tree = ast.parse(candidate.source_code)
                fn, = tree.body
                ret, = fn.body
                if not isinstance(fn, ast.FunctionDef) or not isinstance(ret, ast.Return):
                    raise ValueError("Demo accepts only a constant return.")
                c = ast.literal_eval(ret.value)
                if type(c) not in (int, float) or not 0 < c <= 1:
                    raise ValueError("Demo parameter must satisfy 0 < c <= 1.")
                result = CandidateEvaluation(candidate.id, True,
                    metrics={"poa": 1/(1-c/4), "equilibrium": c, "optimum": c-c*c/4},
                    behavioral_descriptor=(c,), passing_cases=1, total_cases=1)
            except (ValueError, TypeError, SyntaxError, AttributeError) as error:
                result = CandidateEvaluation(candidate.id, False, failure_stage="demo_validation",
                    failure_reasons=(str(error),), repairable=True, informative=True, total_cases=1)
            self.publish_evaluation(result)
            return result
        return tuple(await asyncio.gather(*(evaluate_one(c) for c in candidates)))
