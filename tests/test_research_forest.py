"""Exercise coordination with real evolution and injected, offline generation ports."""
import asyncio
from dataclasses import replace
from types import SimpleNamespace

from the_pigeon_holes.evolution.models import CandidateEvaluation
from the_pigeon_holes.ui.bridge import LabRun
from the_pigeon_holes.ui.demo import demo_contract, DemoEvaluator, DemoGenerator
from the_pigeon_holes.ui.forest import ResearchForest, PooledPort
from the_pigeon_holes.ui.storage import ArtifactStore


def state(generation, value):
    return SimpleNamespace(generation=generation, global_best_id='candidate-000000',
        evaluations={'candidate-000000': CandidateEvaluation('candidate-000000', True, {'poa': value})})


def test_triggers_are_per_tree_deduplicated_and_cumulative(tmp_path):
    forest = ResearchForest(ArtifactStore(tmp_path / 'archive.db'))
    run = LabRun(delay=0)
    forest.attach(run)
    forest.committed(run, state(0, 1.0))
    for generation in range(1, 10):
        forest.committed(run, state(generation, 1.0))
    assert [d['reasons'] for d in forest.discoveries] == [['new_tree']]
    forest.committed(run, state(10, 1.02))
    forest.committed(run, state(10, 1.02))
    assert forest.discoveries[-1]['reasons'] == ['ten_iterations', 'material_improvement']
    assert len(forest.discoveries) == 2
    forest.committed(run, state(11, 1.025))
    assert len(forest.discoveries) == 2
    forest.committed(run, state(12, 1.04))
    assert forest.discoveries[-1]['reasons'] == ['material_improvement']


def test_minimize_and_invalid_evidence_never_trigger_improvement(tmp_path):
    forest = ResearchForest(ArtifactStore(tmp_path / 'archive.db'))
    run = LabRun(delay=0)
    run.contract = replace(run.contract, optimisation_goal=replace(run.contract.optimisation_goal,
        primary=replace(run.contract.optimisation_goal.primary, direction='minimize')))
    forest.attach(run)
    forest.committed(run, state(0, 10.0))
    forest.committed(run, state(1, 11.0))
    invalid = state(2, 1.0)
    invalid.evaluations['candidate-000000'] = CandidateEvaluation('candidate-000000', False)
    forest.committed(run, invalid)
    assert len(forest.discoveries) == 1
    forest.committed(run, state(3, 9.0))
    assert forest.discoveries[-1]['reasons'] == ['material_improvement']


def test_two_trees_exchange_prompt_evidence_and_record_evaluated_descendants(tmp_path):
    async def scenario():
        store = ArtifactStore(tmp_path / 'archive.db')
        forest = ResearchForest(store)
        prompts = []
        class RecordingGenerator(DemoGenerator):
            async def generate(self, requests):
                prompts.extend(r.prompt for r in requests)
                return await super().generate(requests)
        def run_for(author):
            contract = replace(demo_contract(), natural_language_spec=f'{author}: selfish routing graph optimization')
            run = LabRun(delay=0, contract=contract, generator=RecordingGenerator(lambda *a: None, .001),
                         evaluator=DemoEvaluator(0), store=store)
            run.snapshot['run']['author'] = author
            forest.attach(run)
            return run
        a, b = run_for('Ada'), run_for('Emmy')
        await asyncio.gather(a.run(), b.run())
        assert all(r.snapshot['run']['status'] == 'completed' for r in (a,b))
        assert forest.bridges
        assert any('CROSS-TREE COLLABORATION TASK' in p for p in prompts)
        complete = [b for b in forest.bridges if b['targetEvidence']]
        assert complete
        for bridge in complete:
            assert bridge['sourceRunId'] != bridge['targetRunId']
            target = forest.runs[bridge['targetRunId']]
            candidate = target.evidence['candidates'][bridge['targetIdeaId']]
            assert 'CROSS-TREE COLLABORATION TASK' in candidate.generation_prompt
            assert bridge['sourceIdeaId'] in forest.runs[bridge['sourceRunId']].evidence['candidates']
            assert bridge['targetEvidence']['candidate_id'] == bridge['targetIdeaId']
        assert all(any(l['category']=='collaboration' for l in r.snapshot['logs']) for r in (a,b))
        view = forest.view()
        assert len(view['trees']) == 2
        assert all('sourceEvidence' not in b for b in view['bridges'])
        assert ResearchForest(store).bridges == forest.bridges
    asyncio.run(scenario())


def test_global_pool_bounds_work_and_releases_after_cancel():
    async def scenario():
        active, peak = 0, 0
        gate = asyncio.Event()
        class Port:
            async def generate(self, requests):
                nonlocal active, peak
                active += 1; peak = max(peak, active)
                try:
                    await gate.wait()
                    return requests
                finally:
                    active -= 1
        pool = asyncio.Semaphore(2)
        port = PooledPort(Port(), pool)
        tasks = [asyncio.create_task(port.generate([i])) for i in range(5)]
        await asyncio.sleep(.01)
        assert active == peak == 2
        tasks[0].cancel()
        gate.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        assert active == 0 and peak == 2
        assert await port.generate([9]) == [9]
    asyncio.run(scenario())


def test_recovery_marks_unfinished_connections_without_rerunning(tmp_path):
    store = ArtifactStore(tmp_path / 'archive.db')
    run = LabRun(delay=0, store=store)
    forest = ResearchForest(store)
    forest.attach(run)
    forest.bridges = [dict(id='bridge', targetRunId=run.id, status='testing')]
    forest.persist()
    restored = ResearchForest(store)
    restored.attach(LabRun.restore(store.get('run', run.id), store), restored=True)
    assert restored.bridges[0]['status'] == 'interrupted'
    assert not restored.requests


def test_api_allows_multiple_running_trees_and_exposes_connections(monkeypatch, tmp_path):
    from the_pigeon_holes.ui import api
    import httpx
    async def scenario():
        store = ArtifactStore(tmp_path / 'archive.db')
        monkeypatch.setattr(api, 'store', store)
        monkeypatch.setattr(api, 'runs', {})
        monkeypatch.setattr(api, 'forest', ResearchForest(store))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app), base_url='http://test') as client:
            a, b = await asyncio.gather(*[client.post('/api/runs', json={'mode':'demo', 'author': name}) for name in ('Ada','Emmy')])
            assert a.status_code == b.status_code == 201
            assert a.json()['id'] != b.json()['id']
            trees = (await client.get('/api/forest')).json()['trees']
            assert {t['author'] for t in trees} == {'Ada','Emmy'}
            assert (await client.get('/api/forest/bridges/missing')).status_code == 404
            await client.post('/api/runs/'+a.json()['id']+'/stop')
            assert api.runs[b.json()['id']].snapshot['run']['status'] == 'running'
            await client.post('/api/runs/'+b.json()['id']+'/stop')
            await asyncio.gather(*(r.task for r in api.runs.values()), return_exceptions=True)
    asyncio.run(scenario())


def test_transfer_deduplication_rejection_and_demo_isolation(tmp_path):
    from the_pigeon_holes.evolution.models import GenerationRequest, EvolutionOperator, MutationStrength
    async def scenario():
        forest = ResearchForest(ArtifactStore(tmp_path / 'archive.db'))
        source = LabRun(delay=0)
        forest.attach(source)
        await source.run()
        target = LabRun(delay=0)
        forest.attach(target)
        forest.discover(target, ['new_tree'], target.id)
        assert len(forest.bridges) == 1
        forest.discover(target, ['ten_iterations'], target.id)
        assert len(forest.bridges) == 1  # One pending transfer, even on repeated triggers.
        request = GenerationRequest('request-1', 1, 'island-1', EvolutionOperator.MUTATE,
                                    MutationStrength.MICRO, (), (), 'Destination constraints')
        enriched = forest.prepare_requests(target, (request,))
        assert enriched[0].prompt.startswith('Destination constraints')
        assert request.prompt == 'Destination constraints'
        bridge = forest.bridges[0]
        seed = next(iter(source.evidence['candidates'].values()))
        candidate = replace(seed, id='candidate-transfer', request_id=request.id)
        forest.candidate_created(target, candidate)
        forest.evaluated(target, CandidateEvaluation(candidate.id, False,
            failure_reasons=('incompatible destination constraints',)))
        assert bridge['status'] == 'rejected'
        assert bridge['targetEvidence']['valid'] is False
        assert source.evidence['candidates'][seed.id] == seed
        attempted = bridge['sourceIdeaId']
        forest.discover(target, ['ten_iterations'], target.id)
        assert all(b['sourceIdeaId'] != attempted for b in forest.bridges[1:])
        real = LabRun(delay=0)
        real.custom = True
        forest.attach(real)
        forest.discover(real, ['new_tree'], real.id)
        assert not any(b['targetRunId'] == real.id for b in forest.bridges)
    asyncio.run(scenario())
