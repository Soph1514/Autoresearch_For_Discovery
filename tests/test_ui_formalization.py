import asyncio
import pytest
from pydantic import ValidationError
from the_pigeon_holes.ui.formalization import FormalizationInput, prepare

class Tools:
    def __init__(self, valid):
        self.valid = iter(valid)
        self.generations = 0
        self.scores = 0
    async def generate(self, problem, feedback=''):
        self.generations += 1
        return 'import Mathlib\ndef answer := 42'
    async def check(self, source):
        return {'valid': next(self.valid), 'diagnostics': 'checker feedback'}
    async def score(self, problem, source):
        self.scores += 1
        return {'fidelity_decision': 'review', 'p_faithful': .5}

def test_formal_bypasses_generation_and_preserves_review():
    tools = Tools([True])
    result = asyncio.run(prepare(FormalizationInput(mode='formal', problem='A problem', lean='def x := 1'), tools))
    assert tools.generations == 0 and tools.scores == 1
    assert result['lean'] == 'def x := 1' and result['status'] == 'review'

def test_generation_keeps_repairing_until_valid():
    tools = Tools([False, False, False, True])
    result = asyncio.run(prepare(FormalizationInput(problem='A problem'), tools))
    assert tools.generations == 4 and result['attempts'] == 4
    assert result['lean_checked']

def test_formal_input_is_repaired_after_failure():
    tools = Tools([False, True])
    result = asyncio.run(prepare(FormalizationInput(mode='formal', problem='A problem', lean='broken'), tools))
    assert result['lean_checked'] and tools.generations == 1

def test_cancel_stops_repairs_without_scoring():
    async def scenario():
        entered = asyncio.Event()
        class Waiting(Tools):
            async def check(self, source):
                entered.set()
                await asyncio.Event().wait()
        tools = Waiting([])
        task = asyncio.create_task(prepare(FormalizationInput(problem='A problem'), tools))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert tools.generations == 1 and tools.scores == 0
    asyncio.run(scenario())

def test_stream_emits_progress_and_releases_lock(monkeypatch):
    import json
    from fastapi.testclient import TestClient
    from the_pigeon_holes.ui import api
    async def prepared(body, progress=None):
        await progress({'stage': 'checking', 'attempt': 3, 'lean': 'source'})
        return {'lean_checked': True, 'attempts': 3}
    monkeypatch.setattr(api, 'prepare', prepared)
    with TestClient(api.app) as client:
        for _ in range(2):
            response = client.post('/api/formalizations?stream=true', json={'problem':'A problem'})
            events = [json.loads(line) for line in response.text.splitlines()]
            assert events[0]['stage'] == 'checking'
            assert events[-1]['result']['attempts'] == 3
            assert not api.formalization_lock.locked()

def test_missing_formal_source_rejected():
    with pytest.raises(ValidationError):
        FormalizationInput(mode='formal', problem='A problem')

def test_fidelity_outage_preserves_checked_source():
    class Offline(Tools):
        async def score(self, problem, source):
            raise RuntimeError('offline')
    result = asyncio.run(prepare(FormalizationInput(mode='formal', problem='A problem', lean='def x := 1'), Offline([True])))
    assert result['lean_checked'] and result['status'] == 'review'
    assert result['lean'] == 'def x := 1' and result['fidelity_error']

def test_demo_page_remains_available():
    from fastapi.testclient import TestClient
    from the_pigeon_holes.ui.api import app
    with TestClient(app) as client:
        response = client.get('/api/demo')
        assert response.status_code == 200
        assert '/api/paper-theme.css' in response.text and 'Idea lineage' in response.text
        assert client.post('/api/formalizations', json={'mode': 'formal', 'problem': 'A problem'}).status_code == 422

def test_disconnect_cancels_stream_worker_and_unlocks(monkeypatch):
    import json
    from the_pigeon_holes.ui import api
    async def scenario():
        disconnected = asyncio.Event()
        cancelled = asyncio.Event()
        async def prepared(body, progress=None):
            try:
                await progress({'stage':'checking', 'attempt':1})
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        monkeypatch.setattr(api, 'prepare', prepared)
        sent = False
        async def receive():
            nonlocal sent
            if not sent:
                sent = True
                return {'type':'http.request', 'body':json.dumps({'problem':'test'}).encode(), 'more_body':False}
            await disconnected.wait()
            return {'type':'http.disconnect'}
        async def send(message):
            if message['type'] == 'http.response.body' and b'progress' in message.get('body', b''):
                disconnected.set()
        scope = {'type':'http', 'asgi':{'version':'3.0','spec_version':'2.0'}, 'method':'POST',
                 'scheme':'http', 'path':'/api/formalizations', 'raw_path':b'/api/formalizations',
                 'query_string':b'stream=true', 'headers':[(b'content-type',b'application/json')],
                 'client':('127.0.0.1',123), 'server':('localhost',80), 'root_path':''}
        await asyncio.wait_for(api.app(scope, receive, send), 3)
        assert cancelled.is_set()
        assert not api.formalization_lock.locked()
    asyncio.run(scenario())

def test_repairs_lean4_refine_goal_hole_without_changing_statement():
    class HoleTools(Tools):
        async def check(self, source):
            return {'valid': ', ?_⟩' in source, 'diagnostics': "don't know how to synthesize placeholder"}
    source = 'theorem witness : ∃ n : Nat, n = 1 := by\n  refine ⟨1, _⟩\n  rfl'
    tools = HoleTools([])
    result = asyncio.run(prepare(FormalizationInput(mode='formal', problem='One exists', lean=source), tools))
    assert result['lean'] == source.replace(', _⟩', ', ?_⟩')
    assert result['attempts'] == 2 and tools.generations == 0
