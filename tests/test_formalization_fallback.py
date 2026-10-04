import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from the_pigeon_holes.ui import formalization as f


def test_healthy_qwen_does_not_call_claude(monkeypatch):
    tools = f.HostedTools()
    monkeypatch.setattr(tools, '_qwen', AsyncMock(return_value='def n : Nat := 1'))
    claude = AsyncMock(side_effect=AssertionError('unexpected Claude call'))
    monkeypatch.setattr(tools, '_claude', claude)
    assert asyncio.run(tools.generate('Problem')) == 'def n : Nat := 1'
    assert tools.fallback_reason is None


def test_fallback_and_repairs_use_claude_and_record_actual_provider(monkeypatch):
    import anthropic
    calls = []
    class Client:
        def __init__(self, **kwargs):
            self.messages = self
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(stop_reason='end_turn',
                content=[SimpleNamespace(type='text', text='```lean\ndef n : Nat := 1\n```')],
                usage=SimpleNamespace(input_tokens=12, output_tokens=8))
    monkeypatch.setattr(anthropic, 'AsyncAnthropic', Client)
    monkeypatch.delenv('FORMALIZATION_FALLBACK_MODEL', raising=False)
    tools = f.HostedTools()
    qwen = AsyncMock(side_effect=RuntimeError('unavailable'))
    monkeypatch.setattr(tools, '_qwen', qwen)
    monkeypatch.setattr(tools, 'check', AsyncMock(side_effect=[
        {'valid': False, 'diagnostics': 'Fix this error'},
        {'valid': True, 'diagnostics': '', 'check_artifact': {'exit_code': 0}},
    ]))
    monkeypatch.setattr(tools, 'score', AsyncMock(side_effect=RuntimeError('unavailable')))
    result = asyncio.run(f.prepare(f.FormalizationInput(problem='My problem'), tools=tools))
    assert qwen.await_count == 1 and len(calls) == 2
    assert 'My problem' in calls[1]['messages'][0]['content']
    assert 'Fix this error' in calls[1]['messages'][0]['content']
    assert result['generator'] == 'claude-sonnet-4-6'
    assert result['lean'] == 'def n : Nat := 1'
    assert result['status'] == 'review' and result['lean_checked']
    assert len(result['generation_calls']) == 2


def test_cancelled_qwen_does_not_start_paid_fallback(monkeypatch):
    tools = f.HostedTools()
    monkeypatch.setattr(tools, '_qwen', AsyncMock(side_effect=asyncio.CancelledError))
    claude = AsyncMock()
    monkeypatch.setattr(tools, '_claude', claude)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(tools.generate('Problem'))
    claude.assert_not_called()


def test_checker_rejection_does_not_trigger_local_recheck(monkeypatch):
    monkeypatch.setattr(f, 'remote_call', AsyncMock(return_value={'valid': False, 'diagnostics': 'invalid'}))
    tools = f.HostedTools()
    assert not asyncio.run(tools.check('bad Lean'))['valid']
    assert not tools.local_checker


def test_checker_outage_uses_local_checker(monkeypatch):
    from the_pigeon_holes.ui import local_lean
    remote = AsyncMock(side_effect=RuntimeError('unavailable'))
    monkeypatch.setattr(f, 'remote_call', remote)
    monkeypatch.setattr(local_lean, 'check', lambda source: {'valid': source == 'ok'})
    tools = f.HostedTools()
    async def scenario():
        assert (await tools.check('ok'))['valid']
        assert not (await tools.check('bad'))['valid']
    asyncio.run(scenario())
    assert tools.local_checker and remote.await_count == 1
