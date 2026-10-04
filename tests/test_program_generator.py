"""Tests for the bounded production Anthropic generation adapter."""

import asyncio
from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from the_pigeon_holes.evolution.models import (
    EvolutionOperator,
    GenerationRequest,
    MutationStrength,
)
from the_pigeon_holes.llm.program_generator import (
    AnthropicGeneratorConfig,
    AnthropicProgramGenerator,
)


def _request(number: int) -> GenerationRequest:
    return GenerationRequest(
        id=f"request-{number}",
        generation=1,
        island_id="island-001",
        operator=EvolutionOperator.MUTATE,
        mutation_strength=MutationStrength.COMPONENT,
        parent_ids=("candidate-0",),
        inspiration_ids=(),
        prompt=f"prompt {number}",
    )


def _response(number: int, *, valid: bool = True, tokens=(10, 5)):
    if valid:
        content = [
            SimpleNamespace(
                type="tool_use",
                name="submit_candidate",
                input={
                    "hypothesis": f"candidate {number}",
                    "predicted_effect": "improve score",
                    "falsification_condition": "score does not improve",
                    "mechanism_tags": ["constructive", str(number)],
                    "source_code": f"def solve(x: int) -> int:\n    return {number}\n",
                },
            )
        ]
        stop_reason = "tool_use"
    else:
        content = [SimpleNamespace(type="text", text="not structured")]
        stop_reason = "end_turn"
    return SimpleNamespace(
        content=content,
        stop_reason=stop_reason,
        usage=SimpleNamespace(input_tokens=tokens[0], output_tokens=tokens[1]),
    )


class _Client:
    def __init__(self, create):
        self.messages = SimpleNamespace(create=create)


def test_generator_preserves_order_ids_usage_and_backend_provenance():
    calls = []

    async def create(**kwargs):
        calls.append(kwargs)
        number = int(kwargs["messages"][0]["content"].rsplit(" ", 1)[1])
        return _response(number)

    generator = AnthropicProgramGenerator(
        AnthropicGeneratorConfig(
            model="test-model",
            max_output_tokens=512,
            max_concurrency=2,
            timeout_seconds=12,
            max_attempts=1,
        ),
        client=_Client(create),
    )
    results = asyncio.run(generator.generate((_request(1), _request(2))))

    assert [result.request_id for result in results] == ["request-1", "request-2"]
    assert [result.draft.hypothesis for result in results] == [
        "candidate 1",
        "candidate 2",
    ]
    assert all(result.usage.total_tokens == 15 for result in results)
    assert all(call["model"] == "test-model" for call in calls)
    assert all(call["max_tokens"] == 512 and call["timeout"] == 12 for call in calls)
    assert all(call["tool_choice"]["name"] == "submit_candidate" for call in calls)
    assert all(call["tool_choice"]["type"] == "tool" for call in calls)
    assert all(call["tools"][0]["input_schema"]["additionalProperties"] is False for call in calls)
    assert all("parent_ids" not in call["tools"][0]["input_schema"]["properties"] for call in calls)


def test_generator_retries_invalid_responses_and_charges_every_attempt():
    responses = iter([_response(1, valid=False, tokens=(7, 3)), _response(1)])
    delays = []

    async def create(**kwargs):
        return next(responses)

    async def sleep(delay):
        delays.append(delay)

    generator = AnthropicProgramGenerator(
        AnthropicGeneratorConfig(
            model="test-model",
            max_attempts=2,
            retry_backoff_seconds=0.25,
        ),
        client=_Client(create),
        sleep=sleep,
    )
    result = asyncio.run(generator.generate((_request(1),)))[0]

    assert result.draft is not None
    assert result.usage.input_tokens == 17
    assert result.usage.output_tokens == 8
    assert delays == [0.25]


def test_generator_returns_one_explicit_failure_after_bounded_attempts():
    calls = 0

    async def create(**kwargs):
        nonlocal calls
        calls += 1
        return _response(1, valid=False)

    generator = AnthropicProgramGenerator(
        AnthropicGeneratorConfig(model="test-model", max_attempts=2),
        client=_Client(create),
        sleep=lambda _: asyncio.sleep(0),
    )
    result = asyncio.run(generator.generate((_request(1),)))[0]

    assert calls == 2
    assert result.draft is None
    assert "exactly one submit_candidate" in result.error
    assert result.usage.total_tokens == 30


def test_generator_retries_transient_provider_errors_without_leaking_details():
    calls = 0

    async def create(**kwargs):
        nonlocal calls
        calls += 1
        raise anthropic.APIConnectionError(
            message="secret upstream address",
            request=httpx2.Request("POST", "https://provider.invalid"),
        )

    generator = AnthropicProgramGenerator(
        AnthropicGeneratorConfig(model="test-model", max_attempts=2),
        client=_Client(create),
        sleep=lambda _: asyncio.sleep(0),
    )
    result = asyncio.run(generator.generate((_request(1),)))[0]

    assert calls == 2
    assert result.error == "provider APIConnectionError"
    assert "secret" not in result.error


def test_generator_bounds_concurrency():
    active = 0
    maximum = 0

    async def create(**kwargs):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        await asyncio.sleep(0.01)
        active -= 1
        return _response(1)

    generator = AnthropicProgramGenerator(
        AnthropicGeneratorConfig(
            model="test-model",
            max_concurrency=2,
            max_attempts=1,
        ),
        client=_Client(create),
    )
    results = asyncio.run(generator.generate(tuple(_request(i) for i in range(5))))

    assert len(results) == 5
    assert maximum == 2


def test_generator_propagates_cancellation():
    started = asyncio.Event()

    async def create(**kwargs):
        started.set()
        await asyncio.Future()

    async def scenario():
        generator = AnthropicProgramGenerator(
            AnthropicGeneratorConfig(model="test-model", max_attempts=1),
            client=_Client(create),
        )
        task = asyncio.create_task(generator.generate((_request(1),)))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())


def test_shared_budget_reserves_prompt_and_output_before_concurrent_calls():
    called = []
    async def count_tokens(**kwargs):
        return SimpleNamespace(input_tokens=10)
    async def create(**kwargs):
        called.append(kwargs)
        await asyncio.sleep(.01)
        return _response(1)
    client = _Client(create)
    client.messages.count_tokens = count_tokens
    generator = AnthropicProgramGenerator(AnthropicGeneratorConfig(
        model='test', max_output_tokens=20, token_budget=30, max_attempts=1), client=client)
    results = asyncio.run(generator.generate((_request(1), _request(2))))
    assert len(called) == 1
    assert results[0].draft is not None
    assert 'token budget' in results[1].error
