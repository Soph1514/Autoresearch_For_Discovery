import asyncio
from types import SimpleNamespace

import pytest

from the_pigeon_holes.ui.formalization import FormalizationInput, prepare
from the_pigeon_holes.ui.lean_repair import repair


class Tools:
    def __init__(self):
        self.drafts = 0
        self.repairs = []
        self.checked = []

    async def generate(self, problem):
        self.drafts += 1
        return 'original draft'

    async def repair(self, problem, original, source, diagnostics):
        self.repairs.append((problem, original, source, diagnostics))
        return f'repair {len(self.repairs)}'

    async def check(self, source):
        self.checked.append(source)
        return {'valid': len(self.checked) == 4, 'diagnostics': f'error {len(self.checked)}'}

    async def score(self, problem, source):
        assert source == 'repair 3'
        return {'fidelity_decision': 'accept'}


@pytest.mark.parametrize('mode', ['natural', 'formal'])
def test_opus_repair_repeats_with_latest_diagnostics_and_original_claim(mode):
    tools = Tools()
    events = []

    async def progress(event):
        events.append(event)

    result = asyncio.run(prepare(FormalizationInput(mode=mode, problem='original problem',
                                                    lean='original draft'), tools, progress))
    assert tools.drafts == (1 if mode == 'natural' else 0)
    assert tools.checked == ['original draft', 'repair 1', 'repair 2', 'repair 3']
    assert [r[3] for r in tools.repairs] == ['error 1', 'error 2', 'error 3']
    assert all(r[:2] == ('original problem', 'original draft') for r in tools.repairs)
    assert result['lean_checked'] and result['attempts'] == 4
    assert result['generator'] == result['repair_model'] == 'claude-opus-5-5'
    assert all(e['model'] == 'claude-opus-5-5' for e in events if e['stage'] == 'repairing')


def test_stop_cancels_an_in_progress_repair():
    entered = asyncio.Event()

    class WaitingTools(Tools):
        async def repair(self, *args):
            entered.set()
            await asyncio.Event().wait()

    async def scenario():
        task = asyncio.create_task(prepare(FormalizationInput(problem='test'), WaitingTools()))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())


def test_opus_adapter_uses_requested_model_and_strips_code_fence(monkeypatch):
    import anthropic
    calls = []

    class Context:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    class Reply(Context):
        async def get_final_message(self):
            return SimpleNamespace(stop_reason='end_turn', content=[
                SimpleNamespace(type='thinking'),
                SimpleNamespace(type='text', text='```lean\nimport Mathlib\n```')])

    class Client(Context):
        def __init__(self, **kwargs):
            self.messages = self

        def stream(self, **kwargs):
            calls.append(kwargs)
            return Reply()

    monkeypatch.setattr(anthropic, 'AsyncAnthropic', Client)
    result = asyncio.run(repair('problem', 'original', 'current', 'diagnostics'))
    assert result == 'import Mathlib'
    assert calls[0]['model'] == 'claude-opus-5-5'
    assert 'original' in calls[0]['messages'][0]['content']
    assert 'diagnostics' in calls[0]['messages'][0]['content']
