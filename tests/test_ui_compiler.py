"""Exercise the frontend's actual HTTP route through compilation and frozen scoring."""
import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from the_pigeon_holes.ui import api, preparation
from the_pigeon_holes.ui.storage import ArtifactStore, contract_from_dict

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / 'problems/lean'


def formalization(source, status='checked'):
    return {'input': {'problem': 'Select a binary list to maximize selected weight within capacity.'},
        'result': {'lean': source, 'lean_checked': True, 'status': status,
            'check_artifact': {'source_sha256': hashlib.sha256(source.encode()).hexdigest(),
                'exit_code': 0, 'toolchain': 'leanprover/lean4:v4.19.0', 'lean_version': '4.19.0',
                'dependencies': {'mathlib': 'pinned'}, 'command': ['lean']}}}


def request_body(identity='checked'):
    return {'formalization_id': identity, 'evaluation_suite_id': 'subset-sum',
        'evaluation_cases': {'seven': {'weights': [3, 4, 5], 'capacity': 7},
                             'four': {'weights': [3, 4, 5], 'capacity': 4}}}


@pytest.fixture(scope='module')
def compiled(tmp_path_factory):
    if not shutil.which('lake') or not (PROJECT / '.lake/packages/mathlib').exists():
        pytest.skip('local Lean/mathlib required')
    if subprocess.run(['lake', 'env', 'lean', '--version'], cwd=PROJECT,
                      capture_output=True, timeout=30).returncode:
        pytest.skip('pinned Lean unavailable')
    store = ArtifactStore(tmp_path_factory.mktemp('ui-compiler') / 'research.sqlite3')
    source = (ROOT / 'problems/subset_sum/Generated.lean').read_text()
    store.put('formalization', 'checked', formalization(source))
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(api, 'store', store)
        patch.setattr(api, 'runs', {})
        patch.setenv('RESEARCH_LEAN_PROJECT', str(PROJECT))
        patch.delenv('RESEARCH_MODEL', raising=False)
        patch.delenv('RESEARCH_API_PASSWORD', raising=False)
        # Compile the saved Lean directly; no generator or interface-extraction call.
        with TestClient(api.app) as client:
            response = client.post('/api/contracts', json=request_body())
            assert response.status_code == 201, response.text
            result = response.json()
            assert result['compiler']['status'] == 'compiled'
            assert result['direction'] == 'maximize'
    return store, result


def test_default_seed_passes_deployed_subset_sum_cases(compiled):
    import asyncio
    from dataclasses import replace
    from the_pigeon_holes.evolution.models import ProgramCandidate, EvolutionOperator
    from the_pigeon_holes.models.problem_contract import EvaluationSuite, EvaluationCase, ResourceLimits

    store, response = compiled
    contract = contract_from_dict(store.get('contract', response['id'])['contract'])
    assert 'return [0] * len(weights)' in contract.seed_program
    cases = {
        'empty': ([], 5), 'textbook': ([3, 4, 5], 7),
        'exact-fit': ([2, 3, 4, 5], 9), 'nothing-fits': ([10, 20, 30], 5),
        'medium': ([1, 2, 3, 4, 5, 6, 7, 8], 20),
        'zero-weights': ([0, 0, 7], 0), 'ties': ([6, 6, 6], 13),
    }
    contract = replace(contract, evaluation_suite=EvaluationSuite('deployed-regression', tuple(
        EvaluationCase(name, {'weights': weights, 'capacity': capacity})
        for name, (weights, capacity) in cases.items())),
        resource_limits=ResourceLimits(30, 180, 512, 100000))
    try:
        evaluator = preparation.make_evaluator(contract, store=store)
    except RuntimeError as error:
        pytest.skip(str(error))
    def candidate(identity, source):
        return ProgramCandidate(identity, 0, None, EvolutionOperator.RESTART, (), (),
            'Initial seed.', 'Baseline.', 'Constraint violation.', ('seed',), source,
            hashlib.sha256(source.encode()).hexdigest())
    old = candidate('old', contract.solve_signature + '\n    return []\n')
    fixed = candidate('fixed', contract.seed_program)
    old_result, fixed_result = asyncio.run(evaluator.evaluate((old, fixed), contract))
    assert not old_result.valid
    assert fixed_result.valid and fixed_result.passing_cases == 7
    assert fixed_result.metrics == {'objective': 0}


def test_explicit_seed_is_preserved(compiled, client):
    body = request_body()
    body['seed_program'] = 'def solve(weights: list[int], capacity: int) -> list[int]:\n    return []\n'
    response = client.post('/api/contracts', json=body)
    assert response.status_code == 201, response.text
    contract = contract_from_dict(api.store.get('contract', response.json()['id'])['contract'])
    assert contract.seed_program == body['seed_program']


@pytest.fixture
def client(compiled, monkeypatch):
    store, _ = compiled
    # A fresh store and registry simulate a backend restart; nothing is cached in memory.
    monkeypatch.setattr(api, 'store', ArtifactStore(store.path))
    monkeypatch.setattr(api, 'runs', {})
    monkeypatch.setenv('RESEARCH_LEAN_PROJECT', str(PROJECT))
    monkeypatch.delenv('RESEARCH_API_PASSWORD', raising=False)
    with TestClient(api.app) as client:
        yield client


def test_compiler_result_and_frozen_scorer_survive_restart(compiled, client, monkeypatch):
    from the_pigeon_holes.evaluation import production
    monkeypatch.setattr(production, 'preflight', lambda *args: 'test-image')
    _, response = compiled
    saved = api.store.get('contract', response['id'])
    contract = contract_from_dict(saved['contract'])
    evaluator = preparation.make_evaluator(contract, store=api.store)
    fitness = evaluator.fitness_function
    assert fitness.reference == contract.fitness_function
    assert len(contract.evaluation_suite.cases) == 2
    assert fitness.evaluate_case(contract.evaluation_suite.cases[0], [1, 1, 0]).metrics == {'objective': 7}
    assert not fitness.evaluate_case(contract.evaluation_suite.cases[1], [1, 1, 0]).valid
    manifest = client.get(f"/api/contracts/{response['id']}/compiler").json()
    assert manifest['status'] == 'accepted'
    assert manifest['validation']['kernel_correspondence']
    assert manifest['english_fidelity'] == 'not_proven'


@pytest.mark.parametrize('real_worker', [False, True], ids=['stub-worker', 'docker-worker'])
def test_compiled_contract_starts_actual_ui_evolution(compiled, client, monkeypatch, real_worker):
    from the_pigeon_holes.evaluation import production
    from the_pigeon_holes.execution.container_runner import WorkerResult
    from the_pigeon_holes.evolution.models import CandidateDraft, GenerationResult, TokenUsage
    monkeypatch.setenv('RESEARCH_MODEL', 'test-model')
    if real_worker:
        try:
            production.preflight()
        except RuntimeError as error:
            pytest.skip(str(error))
    else:
        monkeypatch.setattr(production, 'preflight', lambda *args: 'test-image')
    async def container(source, entry, inputs, *args):
        # Only the Docker boundary is stubbed; all validity/objective checks run in Lean.
        if 'return [0] * len(weights)' in source:
            return WorkerResult(True, [0] * len(inputs['weights']))
        return WorkerResult(True, [1, 1, 0] if inputs['capacity'] >= 7 else [0, 1, 0])
    if not real_worker:
        monkeypatch.setattr(production, 'run_candidate_async', container)
    monkeypatch.setattr(preparation, 'compile_fitness', lambda **kwargs: pytest.fail('run start recompiled scorer'))
    class Generator:
        def __init__(self, config, *, budget):
            self.config = config
            self.budget = budget
        async def generate(self, requests):
            return [GenerationResult(r.id, TokenUsage(4096, 4096), CandidateDraft(
                'Use a feasible selection.', 'Larger weight.', 'Capacity exceeded.', ('selection',),
                'def solve(weights: list[int], capacity: int) -> list[int]:\n'
                '    return [1, 1, 0] if capacity >= 7 else [0, 1, 0]\n')) for r in requests]
        async def aclose(self):
            pass
    monkeypatch.setattr(api, 'AnthropicProgramGenerator', Generator)
    response = client.post('/api/runs', json={'mode': 'custom', 'contract_id': compiled[1]['id'],
        'max_tokens': 8192, 'max_time_seconds': 120, 'literature_review': False})
    assert response.status_code == 201, response.text
    identity = response.json()['id']
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        snapshot = client.get(f'/api/runs/{identity}').json()
        if snapshot['run']['status'] in ('completed', 'failed', 'stopped'):
            break
        time.sleep(.1)
    assert snapshot['run']['status'] == 'completed', snapshot
    assert snapshot['run']['contract']['fitnessSource'] == 'Lean compiler'
    artifact = client.get(f'/api/runs/{identity}/artifact').json()
    assert artifact['outcome']['best_evaluation']['metrics']['objective'] == 5.5
    assert artifact['provenance']['compiler']['status'] == 'compiled'
    summary = client.get(f'/api/runs/{identity}/summary').json()
    assert summary['compiler']['status'] == 'compiled'
    assert summary['contract_id'] == compiled[1]['id']
    assert artifact['evidence']['numerical']
    digests = {record['fitness_function']['implementation_sha256']
               for record in artifact['evidence']['numerical'].values()}
    assert digests == {compiled[1]['fitness_function']['implementation_sha256']}


def test_registered_family_skips_compiler_and_uses_baseline(client, monkeypatch):
    monkeypatch.setattr(preparation, 'compile_fitness', lambda **kwargs: pytest.fail('compiler invoked'))
    body = request_body()
    body.update(fitness_function_id='knapsack', fitness_function_version='exact-v1',
        evaluation_cases={'one': {'capacity': 4, 'weights': [2, 4], 'values': [3, 9]}})
    response = client.post('/api/contracts', json=body)
    assert response.status_code == 201, response.text
    assert response.json()['compiler'] is None
    assert response.json()['fitness_function']['id'] == 'knapsack'
    assert client.get(f"/api/contracts/{response.json()['id']}/compiler").status_code == 404
    body['evaluation_cases']['one']['capacity'] = -1
    assert client.post('/api/contracts', json=body).status_code == 422
    body['fitness_function_id'] = 'unknown'
    assert client.post('/api/contracts', json=body).status_code == 422


def test_compiler_rejection_reaches_frontend_with_stage(client):
    api.store.put('formalization', 'unsupported', formalization('def scalar : Nat := 7'))
    response = client.post('/api/contracts', json=request_body('unsupported'))
    assert response.status_code == 422
    assert response.json()['detail']['stage'] == 'unsupported_formalization'
    assert 'optimization declaration' in response.json()['detail']['message']


def test_review_and_source_binding_still_gate_compilation(client, monkeypatch):
    monkeypatch.setattr(preparation, 'compile_fitness', lambda **kwargs: pytest.fail('compiler invoked'))
    artifact = formalization('def scalar : Nat := 7', status='review')
    api.store.put('formalization', 'review', artifact)
    response = client.post('/api/contracts', json=request_body('review'))
    assert response.status_code == 422 and 'Review the Lean' in response.json()['detail']
    artifact['result']['lean'] += '\n-- changed'
    api.store.put('formalization', 'changed', artifact)
    response = client.post('/api/contracts', json=request_body('changed'))
    assert response.status_code == 422 and 'matching Lean check' in response.json()['detail']
