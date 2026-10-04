"""Exercise production orchestration with injected ports, without running candidate code."""
import asyncio
import hashlib
import pytest
from the_pigeon_holes.evolution.models import EvolutionLimits, CandidateEvaluation
from the_pigeon_holes.ui.bridge import LabRun
from the_pigeon_holes.ui.demo import demo_contract, DemoGenerator, DemoEvaluator
from the_pigeon_holes.ui.storage import ArtifactStore, contract_from_dict, pack_inputs, unpack_inputs
from the_pigeon_holes.ui.preparation import ContractInput, prepare_contract


def test_contract_storage_preserves_input_types(tmp_path):
    value = {'nested': [(1, {2: 'x'})], 'kind': 'tuple'}
    assert unpack_inputs(pack_inputs(value)) == value
    contract = demo_contract()
    store = ArtifactStore(tmp_path / 'runs.sqlite3')
    store.put('contract', 'test', contract)
    assert contract_from_dict(store.get('contract', 'test')) == contract


def test_custom_run_evidence_survives_restart(tmp_path):
    async def scenario():
        store = ArtifactStore(tmp_path / 'runs.sqlite3')
        run = LabRun(contract=demo_contract(), generator=DemoGenerator(lambda *args: None, 0),
            evaluator=DemoEvaluator(0), store=store)
        await run.run()
        assert run.snapshot['run']['backend'] == 'python'
        assert run.snapshot['run']['status'] == 'completed'
        assert run.outcome['best_candidate']
        restored = LabRun.restore(store.get('run', run.id), store)
        assert restored.snapshot == run.snapshot
        assert restored.events == run.events
        assert 'Analytic Pigou' not in restored.snapshot['experiments'][0]['feedback']
    asyncio.run(scenario())


def test_invalid_seed_never_calls_generator():
    class Invalid:
        async def evaluate(self, candidates, problem):
            return [CandidateEvaluation(c.id, False, failure_reasons=('Invalid baseline',)) for c in candidates]
    class Never:
        async def generate(self, requests):
            pytest.fail('generation must not begin after a rejected seed')
    async def scenario():
        run = LabRun(contract=demo_contract(), generator=Never(), evaluator=Invalid())
        await run.run()
        assert run.snapshot['run']['status'] == 'failed'
        assert run.outcome['stop_reason'] == 'invalid_seed'
    asyncio.run(scenario())


def test_deadline_cancels_evaluator_and_retains_evidence(tmp_path):
    cancelled = []
    class Slow:
        async def evaluate(self, candidates, problem):
            try:
                await asyncio.sleep(10)
            finally:
                cancelled.append(True)
    async def scenario():
        run = LabRun(contract=demo_contract(), generator=object(), evaluator=Slow(),
            limits=EvolutionLimits(max_time_seconds=.01), store=ArtifactStore(tmp_path / 'runs.sqlite3'))
        await run.run()
        assert cancelled
        assert run.outcome['stop_reason'] == 'time_limit'
        assert not any(e['status'] == 'running' for e in run.snapshot['experiments'])
    asyncio.run(scenario())


def test_restart_marks_active_attempts_interrupted(tmp_path):
    store = ArtifactStore(tmp_path / 'runs.sqlite3')
    run = LabRun(store=store)
    run.emit('experiment_updated', {'id': 'eval-x', 'ideaId': 'x', 'status': 'running', 'valid': None})
    restored = LabRun.restore(store.get('run', run.id), store)
    assert restored.snapshot['run']['status'] == 'stopped'
    assert restored.snapshot['experiments'][0]['status'] == 'cancelled'
    assert [e['sequence'] for e in restored.events] == list(range(1, restored.snapshot['sequence'] + 1))


def test_preparation_rejects_unbound_or_unreviewed_lean(monkeypatch):
    contract = demo_contract()
    body = ContractInput(formalization_id='f', seed_program=contract.seed_program,
        evaluation_suite_id='test', evaluation_cases={'one': {}}, evaluator_version='test')
    result = {'lean_checked': True, 'lean': contract.lean_specification, 'status': 'review'}
    artifact = {'input': {'problem': 'test'}, 'result': result}
    async def scenario():
        with pytest.raises(ValueError, match='matching Lean check'):
            await prepare_contract(body, artifact)
        result['check_artifact'] = {'source_sha256': hashlib.sha256(result['lean'].encode()).hexdigest(),
            'exit_code': 0, 'toolchain': 'test', 'lean_version': 'test', 'dependencies': {'mathlib': 'revision'}, 'command': ['lean']}
        with pytest.raises(ValueError, match='Review the Lean'):
            await prepare_contract(body, artifact)
        monkeypatch.setenv('RESEARCH_MODEL', 'test-model')
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-no-network')
        seen = []
        def builder(**kwargs):
            seen.append(kwargs)
            return contract
        body.alignment_reviewed = True
        assert await prepare_contract(body, artifact, builder=builder) == contract
        assert seen[0]['lean_specification'] == result['lean']
    asyncio.run(scenario())


def test_api_persists_formalization_and_fails_closed_when_evaluator_unavailable(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from the_pigeon_holes.ui import api
    monkeypatch.setattr(api, 'store', ArtifactStore(tmp_path / 'api.sqlite3'))
    monkeypatch.setattr(api, 'runs', {})
    monkeypatch.setenv('RESEARCH_MODEL', 'test')
    def unavailable(contract):
        raise RuntimeError('Python evaluator is not connected.')
    monkeypatch.setattr(api, 'make_evaluator', unavailable)
    async def prepared(body, progress=None):
        return {'lean': 'theorem example : True := by trivial', 'lean_checked': True, 'status': 'review'}
    monkeypatch.setattr(api, 'prepare', prepared)
    with TestClient(api.app) as client:
        response = client.post('/api/formalizations', json={'problem': 'test'})
        assert response.status_code == 200
        identity = response.json()['formalization_id']
        assert api.store.get('formalization', identity)['input']['problem'] == 'test'
        api.store.put('contract', 'ready', {'contract': demo_contract(), 'provenance': {}})
        response = client.post('/api/runs', json={'mode': 'custom', 'contract_id': 'ready'})
        assert response.status_code == 503
        assert 'evaluator is not connected' in response.json()['detail']
        assert not api.runs


def test_metrics_reject_conflicts_and_duplicate_rows(tmp_path):
    from the_pigeon_holes.formalization.metrics import read_metrics
    path = tmp_path / 'metrics.csv'
    path.write_text('problem_id,result\n<<<<<<< upstream\n')
    with pytest.raises(ValueError, match='merge conflict'):
        read_metrics(path)
    path.write_text('problem_id,result\nx,equivalent\nx,not_proven\n')
    with pytest.raises(ValueError, match='Duplicate'):
        read_metrics(path)


def test_optional_auth_protects_read_and_write_endpoints(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from the_pigeon_holes.ui import api
    monkeypatch.setattr(api, 'store', ArtifactStore(tmp_path / 'auth.sqlite3'))
    monkeypatch.setattr(api, 'runs', {})
    monkeypatch.setenv('RESEARCH_API_PASSWORD', 'test-password')
    with TestClient(api.app) as client:
        assert client.get('/api/health').status_code == 401
        assert client.post('/api/runs', json={'mode': 'demo'}).status_code == 401
        assert client.get('/api/health', auth=('research', 'test-password')).status_code == 200


def test_api_custom_contract_to_completed_run_and_replay(tmp_path, monkeypatch):
    import time
    from fastapi.testclient import TestClient
    from the_pigeon_holes.ui import api
    monkeypatch.setattr(api, 'store', ArtifactStore(tmp_path / 'integrated.sqlite3'))
    monkeypatch.setattr(api, 'runs', {})
    monkeypatch.setenv('RESEARCH_MODEL', 'test')
    monkeypatch.delenv('RESEARCH_API_PASSWORD', raising=False)
    async def prepare(body, artifact):
        return demo_contract()
    monkeypatch.setattr(api, 'prepare_contract', prepare)
    monkeypatch.setattr(api, 'make_evaluator', lambda contract: DemoEvaluator(0))
    monkeypatch.setattr(api, 'AnthropicProgramGenerator', lambda config: DemoGenerator(lambda *args: None, 0))
    api.store.put('formalization', 'checked', {'result': {'check_artifact': {'test': True}}})
    with TestClient(api.app) as client:
        prepared = client.post('/api/contracts', json={'formalization_id': 'checked',
            'seed_program': demo_contract().seed_program, 'evaluation_suite_id': 'test',
            'evaluation_cases': {'case': {}}, 'evaluator_version': 'test'})
        assert prepared.status_code == 201
        response = client.post('/api/runs', json={'mode': 'custom',
            'contract_id': prepared.json()['id'], 'max_tokens': 8192})
        assert response.status_code == 201
        identity = response.json()['id']
        for _ in range(100):
            snapshot = client.get(f'/api/runs/{identity}').json()
            if snapshot['run']['status'] == 'completed':
                break
            time.sleep(.01)
        assert snapshot['run']['status'] == 'completed'
        artifact = client.get(f'/api/runs/{identity}/artifact').json()
        assert artifact['outcome']['best_candidate']
        assert artifact['evidence']['candidates']
        assert len(artifact['events']) == snapshot['sequence']
        replay = client.get(f'/api/runs/{identity}/events?after=0')
        assert replay.text.count('data: ') == snapshot['sequence']
    monkeypatch.setattr(api, 'runs', {})
    with TestClient(api.app) as client:
        assert client.get(f'/api/runs/{identity}').json() == snapshot
