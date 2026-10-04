"""The instance stays separate from the general specification and requires review."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from the_pigeon_holes.ui.formalization import FormalizationInput, prepare
from the_pigeon_holes.ui.instance import generate_instance


@pytest.mark.parametrize('mode', ['natural', 'formal'])
def test_general_problem_only_goes_to_lean_and_fidelity(mode):
    tools = SimpleNamespace(generate=AsyncMock(return_value='checked Lean'),
        check=AsyncMock(return_value={'valid': True, 'diagnostics': ''}),
        score=AsyncMock(return_value={'fidelity_decision': 'accept'}))
    convert = AsyncMock(return_value={'evaluation_cases': {'instance': {'weights': [3, 4, 5], 'capacity': 7}}})
    body = FormalizationInput(mode=mode, problem='General subset sum',
        instance='Weights 3, 4, 5; capacity 7.', lean='checked Lean')
    result = asyncio.run(prepare(body, tools=tools, instance_generator=convert))
    if mode == 'natural':
        tools.generate.assert_awaited_once_with(body.problem)
    else:
        tools.generate.assert_not_called()
    tools.score.assert_awaited_once_with(body.problem, 'checked Lean')
    convert.assert_awaited_once_with(body.problem, 'checked Lean', body.instance)
    assert result['instance'] == body.instance
    assert result['evaluation_cases']['instance']['capacity'] == 7


def test_failed_conversion_preserves_checked_lean_and_does_not_create_starter_cases():
    tools = SimpleNamespace(generate=AsyncMock(return_value='Lean'),
        check=AsyncMock(return_value={'valid': True, 'diagnostics': ''}),
        score=AsyncMock(return_value={'fidelity_decision': 'accept'}))
    result = asyncio.run(prepare(FormalizationInput(problem='General', instance='Specific'),
        tools=tools, instance_generator=AsyncMock(side_effect=RuntimeError('provider down'))))
    assert result['lean'] == 'Lean' and result['lean_checked']
    assert result['evaluation_cases'] is None and result['instance_error']


@pytest.mark.parametrize('inputs,error', [({'weights': [3, 4, 5], 'capacity': 7}, ''),
                                         ({}, 'Please specify the capacity.')])
def test_instance_converter_structured_response(monkeypatch, inputs, error):
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
            return SimpleNamespace(stop_reason='tool_use', content=[SimpleNamespace(
                type='tool_use', name='instance_inputs', input={'inputs': inputs, 'error': error})],
                usage=SimpleNamespace(input_tokens=15, output_tokens=20))
    monkeypatch.setattr(anthropic, 'AsyncAnthropic', Client)
    result = asyncio.run(generate_instance('General', 'Checked Lean', 'Specific values'))
    assert calls[0]['tool_choice']['name'] == 'instance_inputs'
    assert 'Checked Lean' in calls[0]['messages'][0]['content']
    assert 'Specific values' in calls[0]['messages'][0]['content']
    assert result['evaluation_cases'] == (None if error else {'instance': inputs})
    assert result['instance_error'] == (error or None)
    assert result['instance_call']['output_tokens'] == 20
