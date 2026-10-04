"""Integration tests for the budgeted evolution orchestration loop."""

import asyncio
import re
from collections.abc import Sequence

import pytest

from the_pigeon_holes.evolution import (
    CandidateDraft,
    CandidateEvaluation,
    EvolutionConfig,
    EvolutionLimits,
    EvolutionLoop,
    EvolutionProtocolError,
    GenerationRequest,
    GenerationResult,
    ProgramCandidate,
    StopReason,
    TokenUsage,
    CandidateDisposition,
)
from the_pigeon_holes.models.problem_contract import (
    EvaluationCase,
    EvaluationSuite,
    FitnessFunctionRef,
    InterfaceDefinition,
    MetricGoal,
    OptimisationGoal,
    Parameter,
    ProblemContract,
    ResourceLimits,
)


CONTRACT = ProblemContract(
    natural_language_spec="Return an integer; higher is better.",
    lean_specification="def solve (x : Int) : Int",
    interface=InterfaceDefinition(
        "python-interface-v1",
        (Parameter("x", "int"),),
        "int",
        "def solve(x: int) -> int:",
    ),
    seed_program="def solve(x: int) -> int:\n    return 0\n",
    evaluation_suite=EvaluationSuite(
        "integer-test", (EvaluationCase("zero", {"x": 0}),)
    ),
    optimisation_goal=OptimisationGoal(MetricGoal("score", "maximize"), "mean"),
    resource_limits=ResourceLimits(1.0, 5.0, 128, 100),
    fitness_function=FitnessFunctionRef("test", "v1", "0" * 64),
)


class _Generator:
    def __init__(self) -> None:
        self.calls: list[tuple[GenerationRequest, ...]] = []

    async def generate(
        self,
        requests: Sequence[GenerationRequest],
    ) -> Sequence[GenerationResult]:
        batch = tuple(requests)
        self.calls.append(batch)
        return tuple(
            GenerationResult(
                request_id=request.id,
                usage=TokenUsage(input_tokens=4, output_tokens=6),
                draft=CandidateDraft(
                    hypothesis=f"Return constant {index}.",
                    predicted_effect="Increase deterministic score.",
                    falsification_condition="Reported score is not the constant.",
                    mechanism_tags=("constant", str(index)),
                    source_code=f"def solve(x: int) -> int:\n    return {index}\n",
                ),
            )
            for index, request in enumerate(batch, start=1)
        )


class _Evaluator:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    async def evaluate(
        self,
        candidates: Sequence[ProgramCandidate],
        problem: ProblemContract,
    ) -> Sequence[CandidateEvaluation]:
        assert problem is CONTRACT
        self.calls.append(tuple(candidate.id for candidate in candidates))
        evaluations = []
        for candidate in candidates:
            match = re.search(r"return (\d+)", candidate.source_code)
            assert match is not None
            score = float(match.group(1))
            evaluations.append(
                CandidateEvaluation(
                    candidate.id,
                    valid=True,
                    metrics={"score": score},
                    behavioral_descriptor=(score, 1.0),
                    passing_cases=1,
                    total_cases=1,
                )
            )
        return evaluations


class _Observer:
    def __init__(self) -> None:
        self.events: list[tuple[str, str | int]] = []

    def candidate_created(self, candidate):
        self.events.append(("candidate_created", candidate.id))

    def evaluation_started(self, candidate):
        self.events.append(("evaluation_started", candidate.id))

    def evaluation_completed(self, evaluation):
        self.events.append(("evaluation_completed", evaluation.candidate_id))

    def generation_failed(self, failure):
        self.events.append(("generation_failed", failure.request_id))

    def state_committed(self, state):
        self.events.append(("state_committed", state.generation))


def test_loop_closes_generation_and_stops_at_reported_token_limit():
    generator = _Generator()
    evaluator = _Evaluator()
    checkpoints = []

    async def checkpoint():
        checkpoints.append(len(generator.calls))

    loop = EvolutionLoop(
        config=EvolutionConfig(
            min_islands=4,
            max_islands=4,
            offspring_per_island=2,
            max_batch_size=16,
            max_tokens_per_request=10,
            random_seed=11,
        ),
        limits=EvolutionLimits(max_tokens=80),
        generator=generator,
        evaluator=evaluator,
        checkpoint=checkpoint,
    )

    outcome = asyncio.run(loop.run(CONTRACT))

    assert outcome.stop_reason is StopReason.TOKEN_LIMIT
    assert outcome.tokens_used == 80
    assert outcome.generations_completed == 1
    assert outcome.candidates_generated == 9
    assert outcome.candidates_evaluated == 9
    assert outcome.best_evaluation is not None
    assert outcome.best_evaluation.metrics["score"] == 8.0
    assert len(generator.calls) == 1
    assert checkpoints == [0]
    assert len(generator.calls[0]) == 8
    assert evaluator.calls[0] == ("candidate-000000",)
    assert len(evaluator.calls[1]) == 8
    first_child = outcome.state.candidates["candidate-000001"]
    assert first_child.request_id == generator.calls[0][0].id
    assert first_child.generation_prompt == generator.calls[0][0].prompt
    assert first_child.generation_usage.total_tokens == 10


def test_exact_duplicates_reuse_canonical_evaluation_without_execution():
    class DuplicateGenerator(_Generator):
        async def generate(self, requests):
            batch = tuple(requests)
            self.calls.append(batch)
            return tuple(
                GenerationResult(
                    request_id=request.id,
                    usage=TokenUsage(4, 6),
                    draft=CandidateDraft(
                        "Repeat the baseline", "Same score", "Source differs",
                        ("constant",), "def solve(x: int) -> int:\n    return 42\n",
                    ),
                )
                for request in batch
            )

    generator = DuplicateGenerator()
    evaluator = _Evaluator()
    loop = EvolutionLoop(
        config=EvolutionConfig(max_tokens_per_request=10),
        limits=EvolutionLimits(max_tokens=80),
        generator=generator,
        evaluator=evaluator,
    )

    outcome = asyncio.run(loop.run(CONTRACT))

    assert evaluator.calls == [("candidate-000000",), ("candidate-000001",)]
    assert outcome.candidates_generated == 9
    assert outcome.candidates_evaluated == 2
    assert len(outcome.state.duplicate_records) == 7
    assert all(
        disposition is CandidateDisposition.DUPLICATE
        for candidate_id, disposition in outcome.state.candidate_dispositions.items()
        if candidate_id not in {"candidate-000000", "candidate-000001"}
    )
    assert all(
        evaluation.reused_from_candidate_id == "candidate-000001"
        for candidate_id, evaluation in outcome.state.evaluations.items()
        if candidate_id not in {"candidate-000000", "candidate-000001"}
    )


def test_seed_evaluation_time_counts_toward_limit():
    now = [0.0]
    generator = _Generator()

    class AdvancingEvaluator(_Evaluator):
        async def evaluate(self, candidates, problem):
            result = await super().evaluate(candidates, problem)
            now[0] += 2.0
            return result

    loop = EvolutionLoop(
        config=EvolutionConfig(max_tokens_per_request=10),
        limits=EvolutionLimits(max_time_seconds=1.0),
        generator=generator,
        evaluator=AdvancingEvaluator(),
        clock=lambda: now[0],
    )

    outcome = asyncio.run(loop.run(CONTRACT))

    assert outcome.stop_reason is StopReason.TIME_LIMIT
    assert outcome.generations_completed == 0
    assert outcome.candidates_generated == 1
    assert generator.calls == []


def test_all_generation_errors_stop_and_preserve_failure_evidence():
    class FailingGenerator(_Generator):
        async def generate(self, requests):
            batch = tuple(requests)
            self.calls.append(batch)
            return tuple(
                GenerationResult(
                    request_id=request.id,
                    usage=TokenUsage(),
                    error="provider retries exhausted",
                )
                for request in batch
            )

    generator = FailingGenerator()
    observer = _Observer()
    loop = EvolutionLoop(
        config=EvolutionConfig(max_tokens_per_request=10),
        limits=EvolutionLimits(max_tokens=80),
        generator=generator,
        evaluator=_Evaluator(),
        observer=observer,
    )

    outcome = asyncio.run(loop.run(CONTRACT))

    assert outcome.stop_reason is StopReason.GENERATION_FAILED
    assert outcome.generations_completed == 0
    assert len(outcome.state.generation_failures) == 8
    assert outcome.state.generation_failures[0].prompt == generator.calls[0][0].prompt
    assert observer.events[:4] == [
        ("candidate_created", "candidate-000000"),
        ("evaluation_started", "candidate-000000"),
        ("evaluation_completed", "candidate-000000"),
        ("state_committed", 0),
    ]
    assert [kind for kind, _ in observer.events].count("generation_failed") == 8


def test_valid_evaluation_must_cover_the_complete_suite():
    class IncompleteEvaluator(_Evaluator):
        async def evaluate(self, candidates, problem):
            return tuple(
                CandidateEvaluation(
                    candidate.id,
                    valid=True,
                    metrics={"score": 1.0},
                )
                for candidate in candidates
            )

    loop = EvolutionLoop(
        config=EvolutionConfig(max_tokens_per_request=10),
        limits=EvolutionLimits(max_tokens=80),
        generator=_Generator(),
        evaluator=IncompleteEvaluator(),
    )

    with pytest.raises(EvolutionProtocolError, match="every evaluation-suite case"):
        asyncio.run(loop.run(CONTRACT))


@pytest.mark.parametrize(
    "limits",
    [
        {"max_time_seconds": float("nan")},
        {"max_time_seconds": float("inf")},
        {"max_tokens": 1.5},
    ],
)
def test_run_limits_reject_non_finite_time_and_non_integer_tokens(limits):
    with pytest.raises(ValueError):
        EvolutionLimits(**limits)
