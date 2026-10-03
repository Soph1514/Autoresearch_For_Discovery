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

def test_generation_repairs_once():
    tools = Tools([False, True])
    result = asyncio.run(prepare(FormalizationInput(problem='A problem'), tools))
    assert tools.generations == 2 and result['attempts'] == 2
    assert result['lean_checked']

def test_invalid_lean_never_scores():
    tools = Tools([False, False])
    result = asyncio.run(prepare(FormalizationInput(problem='A problem'), tools))
    assert result['status'] == 'invalid' and tools.scores == 0

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
