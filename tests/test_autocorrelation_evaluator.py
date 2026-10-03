"""Container-backed tests for the stage 0 autocorrelation evaluator.

These run real candidate code in Docker. They are skipped when the daemon or
the worker image is unavailable, so the rest of the suite runs without Docker.
"""

import asyncio

import pytest

from the_pigeon_holes.evaluation.production import AutocorrelationEvaluator
from the_pigeon_holes.evolution.models import EvolutionOperator, ProgramCandidate
from the_pigeon_holes.execution.container_runner import ContainerLimits, preflight
from the_pigeon_holes.execution.signature_extractor import MetricGoal, OptimisationGoal, Parameter
from the_pigeon_holes.judging.autocorrelation import JUDGE_VERSION
from the_pigeon_holes.models.problem_contract import (
    EvaluationCase,
    EvaluationSuite,
    InterfaceDefinition,
    ProblemContract,
    ResourceLimits,
)

SIGNATURE = "def solve(n: int) -> list[int]:"
SEED = "def solve(n: int) -> list[int]:\n    return [2**40] * n\n"


def contract(n=64):
    return ProblemContract(
        natural_language_spec="Minimise the autoconvolution ratio C1 of a step function.",
        lean_specification="-- placeholder pending formalisation review",
        interface=InterfaceDefinition(
            "python-interface-v1", (Parameter("n", "int"),), "list[int]", SIGNATURE
        ),
        seed_program=SEED,
        evaluation_suite=EvaluationSuite("autocorr", (EvaluationCase(f"n-{n}", {"n": n}),)),
        optimisation_goal=OptimisationGoal(MetricGoal("c1", "minimize"), "mean"),
        resource_limits=ResourceLimits(5.0, 10.0, 128, 1),
        evaluator_version=JUDGE_VERSION,
    )


def candidate(index, source):
    return ProgramCandidate(
        id=f"c{index}",
        generation=0,
        island_id=None,
        operator=EvolutionOperator.RESTART,
        parent_ids=(),
        inspiration_ids=(),
        hypothesis="h",
        predicted_effect="p",
        falsification_condition="f",
        mechanism_tags=("t",),
        source_code=source,
        source_fingerprint=str(index),
    )


@pytest.fixture(scope="module")
def evaluator():
    try:
        preflight()
    except RuntimeError as error:
        pytest.skip(str(error))
    return AutocorrelationEvaluator(ContainerLimits(memory_mb=128, timeout_seconds=3))


def run(evaluator, sources, problem=None):
    candidates = [candidate(i, source) for i, source in enumerate(sources)]
    return asyncio.run(evaluator.evaluate(candidates, problem or contract()))


def test_seed_is_valid_with_exact_constant_score(evaluator):
    (result,) = run(evaluator, [SEED])
    assert result.valid
    assert result.metrics["c1"] == pytest.approx(2.0)


def test_failures_map_to_stages(evaluator):
    results = run(
        evaluator,
        [
            "def solve(n: int) -> list[int]:\n    raise ValueError('boom')\n",
            "def solve(n: int) -> list[int]:\n    while True: pass\n",
            "def solve(n: int) -> list[int]:\n    return [1.5] * n\n",
            "def solve(x: int) -> list[int]:\n    return [1] * x\n",
            "def solve(n: int) -> list[int]:\n    return [0] * n\n",
        ],
    )
    stages = [result.failure_stage for result in results]
    assert stages == ["crash", "timeout", "invalid_output", "static_validation", "invalid_output"]
    assert all(not result.valid for result in results)


def test_wrong_length_is_rejected(evaluator):
    (result,) = run(evaluator, ["def solve(n: int) -> list[int]:\n    return [2**40] * (n - 1)\n"])
    assert result.failure_stage == "invalid_output"
    assert "expected length" in result.failure_reasons[0]


def test_stdout_noise_does_not_corrupt_the_result(evaluator):
    source = "def solve(n: int) -> list[int]:\n    print('noise')\n    return [2**40] * n\n"
    (result,) = run(evaluator, [source])
    assert result.valid


def test_descriptor_cell_is_reported_for_valid_candidates(evaluator):
    (result,) = run(evaluator, [SEED])
    assert result.behavioral_descriptor == (3.0, 1.0)
