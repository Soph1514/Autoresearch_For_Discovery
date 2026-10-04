"""Two independent syntheses and the advisory critic. Stubbed clients, no network."""

import asyncio
from unittest.mock import MagicMock

import anthropic
import pytest

from the_pigeon_holes.execution.signature_extractor import (
    ExtractedInterface,
    MetricGoal,
    OptimisationGoal,
    Parameter,
)
from the_pigeon_holes.fitness.synthesis.critic import ScorerCritic
from the_pigeon_holes.fitness.synthesis.generator import (
    ScorerCandidate,
    ScorerGenerator,
    ScorerSynthesisConfig,
    render_prompt,
)

GOAL = OptimisationGoal(MetricGoal("total_value", "maximize"), "sum")
INTERFACE = ExtractedInterface(
    function_name="solve",
    parameters=[Parameter("capacity", "int")],
    return_type="list[int]",
    signature_str="def solve(capacity: int) -> list[int]:",
    pydantic_classes_code="",
    optimisation_goal=GOAL,
)
SCORER = """
def validate(output, capacity):
    if not isinstance(output, list):
        return "return a list"
    return None

def score(output, capacity):
    return {"total_value": sum(output)}

def descriptor(output, capacity):
    return (float(len(output)),)
"""


def _tool_response(name, payload, usage=(10, 20)):
    block = MagicMock()
    block.type = "tool_use"
    block.name = name
    block.input = payload
    response = MagicMock()
    response.content = [block]
    response.stop_reason = "tool_use"
    response.usage = MagicMock(input_tokens=usage[0], output_tokens=usage[1])
    return response


def _scorer_payload(**overrides):
    payload = {
        "source_code": SCORER,
        "metric_names": ["total_value"],
        "descriptor_arity": 1,
        "descriptor_axes": [{"name": "length", "lo": 0.0, "hi": 100.0}],
        "validity_rules": ["output must be a list"],
        "objective_derivation": "sum of the selected values",
        "reconciliation_notes": "",
    }
    payload.update(overrides)
    return payload


def _client(responses):
    client = MagicMock()
    client.messages.create = MagicMock(side_effect=list(responses))

    async def create(**kwargs):
        return client.messages.create(**kwargs)

    client.messages.create_async = create
    return client


class _AsyncClient:
    """Minimal async stand-in; records every request it is given."""

    def __init__(self, handler):
        self.requests = []
        self._handler = handler
        self.messages = self

    async def create(self, **kwargs):
        self.requests.append(kwargs)
        result = self._handler(len(self.requests) - 1, kwargs)
        if isinstance(result, Exception):
            raise result
        return result


async def _noop(_seconds):
    return None


# --- generator ---------------------------------------------------------------

def test_synthesis_uses_two_models_and_two_framings():
    client = _AsyncClient(lambda index, kwargs: _tool_response("submit_scorer", _scorer_payload()))
    generator = ScorerGenerator(ScorerSynthesisConfig(), client=client, sleep=_noop)

    a, b = asyncio.run(generator.synthesise(
        problem="Pick items.", lean_source="def solve", interface=INTERFACE))

    assert (a.slot, b.slot) == ("a", "b")
    assert a.model != b.model
    assert a.framing == "lean_primary" and b.framing == "spec_primary"
    assert {request["model"] for request in client.requests} == {a.model, b.model}
    prompts = [request["messages"][0]["content"] for request in client.requests]
    assert prompts[0] != prompts[1]
    assert a.usable and b.usable


def test_synthesis_never_forces_tool_choice_and_uses_strict_tools():
    client = _AsyncClient(lambda index, kwargs: _tool_response("submit_scorer", _scorer_payload()))
    generator = ScorerGenerator(ScorerSynthesisConfig(), client=client, sleep=_noop)
    asyncio.run(generator.synthesise(problem="p", lean_source="l", interface=INTERFACE))

    for request in client.requests:
        assert request["tool_choice"]["type"] == "auto"
        assert request["tools"][0]["strict"] is True


def test_a_candidate_failing_the_static_gate_is_recorded_not_raised():
    payload = _scorer_payload(source_code="import numpy\n" + SCORER)
    client = _AsyncClient(lambda index, kwargs: _tool_response("submit_scorer", payload))
    generator = ScorerGenerator(ScorerSynthesisConfig(), client=client, sleep=_noop)

    a, _ = asyncio.run(generator.synthesise(problem="p", lean_source="l", interface=INTERFACE))

    assert not a.usable
    assert any("outside the allowed standard library" in problem for problem in a.static_problems)
    assert a.error is None


def test_declared_arity_must_match_the_declared_axes():
    payload = _scorer_payload(descriptor_arity=2)
    client = _AsyncClient(lambda index, kwargs: _tool_response("submit_scorer", payload))
    generator = ScorerGenerator(ScorerSynthesisConfig(), client=client, sleep=_noop)

    a, _ = asyncio.run(generator.synthesise(problem="p", lean_source="l", interface=INTERFACE))

    assert any("declared axes" in problem for problem in a.static_problems)


def test_a_provider_failure_on_one_side_leaves_the_other_usable():
    error = anthropic.APIConnectionError(request=MagicMock())

    def handler(index, kwargs):
        return error if kwargs["model"] == ScorerSynthesisConfig().lean_primary_model else \
            _tool_response("submit_scorer", _scorer_payload())

    client = _AsyncClient(handler)
    generator = ScorerGenerator(ScorerSynthesisConfig(max_attempts=2), client=client, sleep=_noop)

    a, b = asyncio.run(generator.synthesise(problem="p", lean_source="l", interface=INTERFACE))

    assert not a.usable and a.error is not None
    assert b.usable


def test_truncated_output_is_an_error_not_a_silent_partial_module():
    response = _tool_response("submit_scorer", _scorer_payload())
    response.stop_reason = "max_tokens"
    client = _AsyncClient(lambda index, kwargs: response)
    generator = ScorerGenerator(ScorerSynthesisConfig(max_attempts=1), client=client, sleep=_noop)

    a, _ = asyncio.run(generator.synthesise(problem="p", lean_source="l", interface=INTERFACE))

    assert a.error is not None and "truncated" in a.error


def test_prompt_carries_the_goal_and_human_feedback_but_no_case_values():
    prompt = render_prompt("FRAMING", problem="Pick items.", lean_source="def solve",
                           interface=INTERFACE, feedback=("validity ignores duplicates",))
    assert "total_value" in prompt and "maximize" in prompt
    assert "validity ignores duplicates" in prompt
    assert "capacity: int" in prompt


# --- critic ------------------------------------------------------------------

def _candidate(slot, **overrides):
    base = dict(slot=slot, model=f"model-{slot}", framing="f", source_code=SCORER,
                metric_names=("total_value",), descriptor_arity=1,
                descriptor_axes=({"name": "length", "lo": 0.0, "hi": 1.0},),
                validity_rules=("must be a list",), objective_derivation="sum")
    base.update(overrides)
    return ScorerCandidate(**base)


def _choice_payload(**overrides):
    payload = {"chosen": "a", "justification": "A matches the Lean predicate",
               "key_differences": ["A rejects duplicates, B allows them"],
               "residual_risks": ["neither checks the capacity bound"],
               "unresolved_ambiguities": ["are duplicate indices allowed?"]}
    payload.update(overrides)
    return payload


def test_critic_returns_a_structured_choice():
    client = _AsyncClient(lambda index, kwargs: _tool_response("submit_choice", _choice_payload()))
    critic = ScorerCritic(model="claude-opus-5-5", client=client)

    choice = asyncio.run(critic.choose(_candidate("a"), _candidate("b"), problem="p",
                                       lean_source="l", interface=INTERFACE))

    assert choice.chosen == "a"
    assert choice.unresolved_ambiguities == ("are duplicate indices allowed?",)
    assert client.requests[0]["tool_choice"]["type"] == "auto"


def test_an_unparseable_critic_reply_leaves_the_choice_open():
    """The human is the authority, so a critic failure must not fail the round."""
    response = MagicMock()
    response.content = []
    response.usage = MagicMock(input_tokens=1, output_tokens=1)
    client = _AsyncClient(lambda index, kwargs: response)
    critic = ScorerCritic(model="claude-opus-5-5", client=client)

    choice = asyncio.run(critic.choose(_candidate("a"), _candidate("b"), problem="p",
                                       lean_source="l", interface=INTERFACE))

    assert choice.chosen is None and choice.error is not None


def test_critic_failure_is_captured_rather_than_raised():
    client = _AsyncClient(lambda index, kwargs: anthropic.APIConnectionError(request=MagicMock()))
    critic = ScorerCritic(model="claude-opus-5-5", client=client)

    choice = asyncio.run(critic.choose(_candidate("a"), _candidate("b"), problem="p",
                                       lean_source="l", interface=INTERFACE))

    assert choice.chosen is None and "APIConnectionError" in choice.error


def test_one_usable_candidate_is_selected_without_a_model_call():
    client = _AsyncClient(lambda index, kwargs: pytest.fail("the critic must not be called"))
    critic = ScorerCritic(model="claude-opus-5-5", client=client)

    choice = asyncio.run(critic.choose(
        _candidate("a"), _candidate("b", static_problems=("missing descriptor()",)),
        problem="p", lean_source="l", interface=INTERFACE))

    assert choice.chosen == "a"
    assert "only one" in choice.justification
    assert client.requests == []


def test_no_usable_candidate_leaves_the_choice_open():
    client = _AsyncClient(lambda index, kwargs: pytest.fail("the critic must not be called"))
    critic = ScorerCritic(model="claude-opus-5-5", client=client)

    choice = asyncio.run(critic.choose(
        _candidate("a", static_problems=("x",)), _candidate("b", static_problems=("y",)),
        problem="p", lean_source="l", interface=INTERFACE))

    assert choice.chosen is None and choice.error is not None


def test_critic_prompt_marks_the_modules_as_untrusted():
    from the_pigeon_holes.fitness.synthesis.critic import render_prompt as critic_prompt

    prompt = critic_prompt(_candidate("a"), _candidate("b"), problem="p", lean_source="l",
                           interface=INTERFACE)
    assert "untrusted data" in prompt
