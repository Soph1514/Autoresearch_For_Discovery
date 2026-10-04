"""Dollar admission must remain safe across models, parallel calls and cancellation."""
import asyncio
from types import SimpleNamespace as NS
import pytest
from the_pigeon_holes.llm.budget import ProviderTokenBudget, TokenBudgetExceeded


def client(create):
    async def count_tokens(**kwargs):
        assert 'output_config' not in kwargs
        return NS(input_tokens=100)
    return NS(messages=NS(count_tokens=count_tokens, create=create))


def test_usd_admission_is_atomic_and_accounts_for_searches():
    async def scenario():
        async def create(**kwargs):
            await asyncio.sleep(.01)
            return NS(usage=NS(input_tokens=100, output_tokens=50, server_tool_use=NS(web_search_requests=1)))
        budget = ProviderTokenBudget(10000, max_cost_usd=.013)
        results = await asyncio.gather(*[budget.create(client(create), model='claude-sonnet-4-6',
            max_tokens=100, max_searches=1) for _ in range(2)], return_exceptions=True)
        assert sum(isinstance(r, TokenBudgetExceeded) for r in results) == 1
        assert budget.summary()['estimated_cost_usd'] == pytest.approx(.01105)
        assert len(budget.calls) == 1
    asyncio.run(scenario())


def test_unknown_billing_keeps_full_reservation_and_unknown_models_fail_closed():
    async def scenario():
        async def fail(**kwargs):
            raise asyncio.CancelledError()
        budget = ProviderTokenBudget(10000, max_cost_usd=1)
        with pytest.raises(asyncio.CancelledError):
            await budget.create(client(fail), model='claude-opus-5-5', max_tokens=100)
        assert budget.summary()['committed_cost_usd'] == .0024
        assert budget.summary()['estimated_cost_usd'] == 0
        with pytest.raises(ValueError, match='verified price'):
            await budget.create(client(fail), model='unknown', max_tokens=100)
    asyncio.run(scenario())


def test_web_search_reservation_includes_internal_context_growth():
    async def scenario():
        async def create(**kwargs):
            pytest.fail('Unaffordable request reached the provider')
        budget = ProviderTokenBudget(5000000, max_cost_usd=1)
        with pytest.raises(TokenBudgetExceeded):
            await budget.create(client(create), model='claude-sonnet-4-6', max_tokens=6000,
                reserve_input_tokens=4000000, reserve_output_tokens=24000, max_searches=3)
        assert not budget.calls
    asyncio.run(scenario())
