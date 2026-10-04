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
    record = evaluator.evidence['c0']
    assert record['mean_c1_exact'] == {'numerator': '2', 'denominator': '1'}
    assert record['cases']['n-64']['output'] == [2**40] * 64


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


def test_top_level_prints_are_discarded(evaluator):
    (result,) = run(evaluator, ["print('module noise')\n" + SEED])
    assert result.valid


def test_streaming_output_limit_is_enforced(evaluator):
    source = "def solve(n: int) -> list[int]:\n    import os\n    while True: os.write(1, b'x' * 65536)\n"
    (result,) = run(evaluator, [source])
    assert result.failure_stage == 'invalid_output'
    assert 'too large' in result.failure_reasons[0]


def test_stop_waits_for_container_removal(evaluator, monkeypatch):
    from the_pigeon_holes.execution import container_runner as runner
    import subprocess
    created = []
    original = runner.run_arguments
    def arguments(name, limits, image):
        created.append(name)
        return original(name, limits, image)
    monkeypatch.setattr(runner, 'run_arguments', arguments)
    async def scenario():
        task = asyncio.create_task(evaluator.evaluate([
            candidate(99, 'def solve(n: int) -> list[int]:\n    while True: pass\n')], contract()))
        for _ in range(100):
            if created:
                result = await asyncio.to_thread(subprocess.run, ['docker', 'inspect', created[0]], capture_output=True)
                if result.returncode == 0:
                    break
            await asyncio.sleep(.02)
        assert created
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        result = await asyncio.to_thread(subprocess.run, ['docker', 'inspect', created[0]], capture_output=True)
        assert result.returncode != 0
    asyncio.run(scenario())


def test_candidate_suite_cases_run_concurrently(evaluator):
    from dataclasses import replace
    problem = replace(contract(),
        evaluation_suite=EvaluationSuite('two', (EvaluationCase('a', {'n': 64}), EvaluationCase('b', {'n': 64}))),
        resource_limits=ResourceLimits(.8, 1.0, 128, 1))
    source = 'def solve(n: int) -> list[int]:\n    import time\n    time.sleep(.55)\n    return [2**40] * n\n'
    (result,) = run(evaluator, [source], problem)
    assert result.valid


def test_case_concurrency_is_globally_bounded_and_candidate_order_is_stable(monkeypatch):
    from dataclasses import replace
    from the_pigeon_holes.evaluation import production
    from the_pigeon_holes.execution.container_runner import WorkerResult

    problem = replace(
        contract(),
        evaluation_suite=EvaluationSuite('three', tuple(
            EvaluationCase(f'n-{n}', {'n': n}) for n in (62, 63, 64)
        )),
    )
    active = peak = 0

    async def fake_run(source, entry_point, args, limits, image):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(.01)
            return WorkerResult(True, output=[2**40] * args['n'])
        finally:
            active -= 1

    async def inline_score(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(production, 'run_candidate_async', fake_run)
    monkeypatch.setattr(production.asyncio, 'to_thread', inline_score)
    local = AutocorrelationEvaluator(
        ContainerLimits(memory_mb=128, timeout_seconds=3),
        max_workers=2,
        check_daemon=False,
    )
    results = run(local, [SEED, SEED], problem)
    assert [result.candidate_id for result in results] == ['c0', 'c1']
    assert all(result.valid and result.passing_cases == 3 for result in results)
    assert peak == 2
    for candidate_id in ('c0', 'c1'):
        evidence = local.evidence[candidate_id]
        assert evidence['mean_c1_exact'] == {'numerator': '2', 'denominator': '1'}
        assert list(evidence['cases']) == ['n-62', 'n-63', 'n-64']
        assert all(case['ok'] and 'c1_exact' in case
                   for case in evidence['cases'].values())


def test_factory_rejects_unsupported_contract_before_docker():
    from dataclasses import replace
    from the_pigeon_holes.evaluation.production import create_evaluator
    with pytest.raises(ValueError, match='mean c1 minimization'):
        create_evaluator(replace(contract(), optimisation_goal=OptimisationGoal(MetricGoal('c1', 'maximize'), 'mean')))
    with pytest.raises(ValueError, match='between'):
        create_evaluator(contract(n=1))


def test_real_evolution_persists_a_known_improving_fixture(evaluator, tmp_path):
    from the_pigeon_holes.evolution.models import CandidateDraft, GenerationResult, TokenUsage, EvolutionConfig, EvolutionLimits
    from the_pigeon_holes.ui.bridge import LabRun
    from the_pigeon_holes.ui.storage import ArtifactStore
    source = ('def solve(n: int) -> list[int]:\n'
              '    import math\n'
              '    return [math.isqrt((2**80) * n // (i + 1)) for i in range(n)]\n')
    class FixtureGenerator:
        async def generate(self, requests):
            return [GenerationResult(r.id, TokenUsage(5, 5), CandidateDraft(
                'Known inverse-square-root fixture', 'Lower c1 than the constant seed',
                'Measured c1 is not lower', ('fixture',), source)) for r in requests]
    async def scenario():
        store = ArtifactStore(tmp_path / 'run.sqlite3')
        run = LabRun(contract=contract(), generator=FixtureGenerator(), evaluator=evaluator, store=store,
            config=EvolutionConfig(min_islands=2, max_islands=2, max_batch_size=2, max_tokens_per_request=10),
            limits=EvolutionLimits(max_tokens=10, max_time_seconds=20))
        await run.run()
        assert run.snapshot['run']['status'] == 'completed'
        assert run.outcome['best_evaluation']['metrics']['c1'] < 2.0
        artifact = store.get('run', run.id)
        assert artifact['outcome']['best_candidate']['source_code'] == source
        assert artifact['evaluator_config']['image'] == evaluator.image
        assert artifact['evidence']['numerical'][artifact['outcome']['best_candidate']['id']]['cases']['n-64']['c1_exact']
        assert 'Not performed' in artifact['snapshot']['run']['contract']['formalVerification']
    asyncio.run(scenario())
