"""The synthesised-scorer adapter, exercised against the real worker container.

Every scorer here is test-authored; nothing executes model output. These tests
skip when Docker or the worker image is unavailable, matching the fixture in
tests/test_construction_fitness.py.
"""

import asyncio
import json
from fractions import Fraction

import pytest

from the_pigeon_holes.execution.container_runner import preflight
from the_pigeon_holes.execution.signature_extractor import (
    ExtractedInterface,
    MetricGoal,
    OptimisationGoal,
    Parameter,
)
from the_pigeon_holes.fitness.registry import FitnessFunctionRegistry
from the_pigeon_holes.fitness.synthesis.adapter import (
    SynthesisedFitnessError,
    freeze_scorer,
    load_synthesised_fitness,
)
from the_pigeon_holes.models.problem_contract import EvaluationCase

GOAL = OptimisationGoal(MetricGoal("total_value", "maximize"), "sum")
INTERFACE = ExtractedInterface(
    function_name="solve",
    parameters=[Parameter("capacity", "int")],
    return_type="list[int]",
    signature_str="def solve(capacity: int) -> list[int]:",
    pydantic_classes_code="",
    optimisation_goal=GOAL,
)
CASE = EvaluationCase("case-1", {"capacity": 10})

GOOD = """
def validate(output, capacity):
    if not isinstance(output, list):
        return "return a list of integers"
    if sum(output) > capacity:
        return "the selection exceeds the capacity"
    return None

def score(output, capacity):
    from fractions import Fraction
    return {"total_value": Fraction(sum(output), 2)}

def descriptor(output, capacity):
    return (float(len(output)),)
"""


@pytest.fixture(scope="module")
def docker_image():
    try:
        return preflight()
    except RuntimeError as error:
        pytest.skip(str(error))


def _freeze(tmp_path, image, source=GOOD, output=(1, 2, 3), **overrides):
    kwargs = dict(
        source=source, statement="Pick items.", lean_source="def solve",
        interface=INTERFACE, metric_names_declared=("total_value",), descriptor_arity=1,
        descriptor_axes=({"name": "length", "lo": 0.0, "hi": 10.0},),
        artifacts=tmp_path, probe_case=CASE, probe_output=list(output),
        review={"decision": "accept", "rounds": 1}, rejected_source="# the other one\n",
        image=image, timeout=60.0,
    )
    kwargs.update(overrides)
    return freeze_scorer(**kwargs)


def test_freeze_probes_through_a_container_and_returns_an_accepted_scorer(tmp_path, docker_image):
    scorer = _freeze(tmp_path, docker_image)

    manifest = scorer.manifest
    assert manifest["status"] == "accepted"
    assert manifest["evidence_tier"] == "lean_checked_synthesised"
    assert manifest["validation"]["valid"] is True
    assert scorer.reference.id == "synth-" + scorer.reference.implementation_sha256
    assert (scorer.artifact / "scorer.py").read_text() == GOOD


def test_scoring_returns_exact_fractions_from_the_container(tmp_path, docker_image):
    scorer = _freeze(tmp_path, docker_image)

    fitness = scorer.evaluate_case(CASE, [1, 3])

    assert fitness.valid
    assert fitness.metrics == {"total_value": Fraction(2, 1)}
    assert fitness.behavioral_descriptor == (2.0,)
    assert fitness.evidence["kernel_checked"] is False
    assert fitness.evidence["evidence_tier"] == "lean_checked_synthesised"


def test_an_infeasible_output_is_invalid_with_the_scorer_s_reason(tmp_path, docker_image):
    scorer = _freeze(tmp_path, docker_image)

    fitness = scorer.evaluate_case(CASE, [50])

    assert not fitness.valid
    assert fitness.failure_reason == "the selection exceeds the capacity"
    assert fitness.evidence["scorer_defect"] is False


def test_a_raising_scorer_is_a_defect_not_an_invalid_candidate(tmp_path, docker_image):
    """Confusing the two would route a broken scorer into the candidate repair path."""
    # Breaks only on one input, so the freeze probe still passes and the defect
    # surfaces during scoring, which is how a latent scorer bug actually behaves.
    broken = GOOD.replace("def validate(output, capacity):\n",
                          "def validate(output, capacity):\n"
                          "    if output == [99]:\n        raise KeyError('boom')\n")
    scorer = _freeze(tmp_path, docker_image, source=broken, output=[1])

    fitness = scorer.evaluate_case(CASE, [99])

    assert not fitness.valid
    assert fitness.evidence["scorer_defect"] is True
    assert "validate" in fitness.failure_reason
    assert "KeyError" in fitness.failure_reason


def test_a_non_stdlib_import_fails_inside_the_container(tmp_path, docker_image):
    """The worker image is bare, so the failure is measured, never a host import."""
    with pytest.raises(SynthesisedFitnessError) as caught:
        _freeze(tmp_path, docker_image, source="import numpy\n" + GOOD)
    assert caught.value.stage == "probe_failed"


def test_editing_the_frozen_scorer_breaks_integrity_and_registry_resolution(tmp_path, docker_image):
    scorer = _freeze(tmp_path, docker_image)
    registry = FitnessFunctionRegistry()
    registry.register(scorer)
    assert registry.resolve(scorer.reference) is scorer

    (scorer.artifact / "scorer.py").write_text(GOOD + "\n# tampered\n")

    with pytest.raises(SynthesisedFitnessError, match="scorer.py changed"):
        scorer._integrity()
    fitness = scorer.evaluate_case(CASE, [1, 3])
    assert not fitness.valid and "changed" in fitness.failure_reason


def test_load_refuses_an_unaccepted_artifact(tmp_path, docker_image):
    scorer = _freeze(tmp_path, docker_image)
    manifest = json.loads((scorer.artifact / "manifest.json").read_text())
    manifest["status"] = "rejected"
    (scorer.artifact / "manifest.json").write_text(json.dumps(manifest))

    with pytest.raises(SynthesisedFitnessError, match="not an accepted scorer"):
        load_synthesised_fitness(scorer.artifact, scorer.reference)


def test_reload_round_trips_a_frozen_scorer(tmp_path, docker_image):
    scorer = _freeze(tmp_path, docker_image)

    reloaded = load_synthesised_fitness(scorer.artifact, scorer.reference)

    assert reloaded.reference == scorer.reference
    assert reloaded.evaluate_case(CASE, [1, 3]).metrics == {"total_value": Fraction(2, 1)}


def test_evaluate_case_works_through_asyncio_to_thread(tmp_path, docker_image):
    """Exactly how SandboxCandidateEvaluator calls it: a nested loop in a worker thread."""
    scorer = _freeze(tmp_path, docker_image)

    async def drive():
        return await asyncio.to_thread(scorer.evaluate_case, CASE, [2, 2])

    fitness = asyncio.run(drive())

    assert fitness.valid and fitness.metrics == {"total_value": Fraction(2, 1)}


def test_evaluate_case_refuses_a_thread_that_already_has_a_loop(tmp_path, docker_image):
    """Misuse by a caller is a programming error, not a scoring outcome."""
    scorer = _freeze(tmp_path, docker_image)

    async def inside():
        return scorer.evaluate_case(CASE, [1])

    with pytest.raises(RuntimeError, match="asyncio.to_thread"):
        asyncio.run(inside())


def test_contract_validation_rejects_a_mismatched_contract(tmp_path, docker_image):
    from dataclasses import replace

    from the_pigeon_holes.models.problem_contract import EvaluationSuite

    scorer = _freeze(tmp_path, docker_image)
    suite = EvaluationSuite("suite-1", (CASE,))
    seed = "def solve(capacity: int) -> list[int]:\n    return []\n"
    contract = scorer.contract(seed_program=seed, evaluation_suite=suite)

    scorer.validate_contract(contract)

    with pytest.raises(ValueError, match="Lean statement"):
        scorer.validate_contract(replace(contract, lean_specification="def other"))


def test_end_to_end_through_the_real_sandbox_evaluator(tmp_path, docker_image):
    """The whole path: candidate container, scorer container, exact aggregation."""
    from the_pigeon_holes.evaluation.production import SandboxCandidateEvaluator
    from the_pigeon_holes.evolution.models import EvolutionOperator, ProgramCandidate
    from the_pigeon_holes.execution.container_runner import ContainerLimits
    from the_pigeon_holes.models.problem_contract import EvaluationSuite

    scorer = _freeze(tmp_path, docker_image)
    suite = EvaluationSuite("suite-1", (EvaluationCase("c1", {"capacity": 10}),
                                        EvaluationCase("c2", {"capacity": 4})))
    seed = "def solve(capacity: int) -> list[int]:\n    return []\n"
    contract = scorer.contract(seed_program=seed, evaluation_suite=suite)
    evaluator = SandboxCandidateEvaluator(
        scorer, ContainerLimits(memory_mb=256, timeout_seconds=60.0),
        image=docker_image, check_daemon=False)

    candidate = ProgramCandidate(
        id="cand-1", generation=0, island_id=None,
        operator=EvolutionOperator.RESTART, parent_ids=(), inspiration_ids=(),
        hypothesis="take one item", predicted_effect="scores 1",
        falsification_condition="rejected", mechanism_tags=("fixed",),
        source_code="def solve(capacity: int) -> list[int]:\n    return [2]\n",
        source_fingerprint="cand-1")

    evaluations = asyncio.run(evaluator.evaluate([candidate], contract))

    assert len(evaluations) == 1
    evaluation = evaluations[0]
    assert evaluation.valid, evaluation.failure_reasons
    # score() halves the sum, so [2] is 1 per case and the goal sums across cases.
    assert evaluation.metrics["total_value"] == pytest.approx(2.0)
    assert evaluation.behavioral_descriptor is not None
    evidence = evaluator.evidence[candidate.id]
    assert evidence["fitness_function"]["id"] == scorer.reference.id
