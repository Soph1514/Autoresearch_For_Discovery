"""Shared token and USD admission, including concurrent and uncertain provider calls."""
import math
from the_pigeon_holes.evolution.models import TokenUsage

# Standard synchronous API list prices, USD / million tokens; verified 2026-10-04.
# Numerically these are also integer microdollars per token. Unknown models fail closed.
MODEL_PRICES = {'claude-opus-5-5': (4, 20), 'claude-opus-4-6': (5, 25),
                'claude-sonnet-4-6': (3, 15)}
PRICING_SOURCE = 'https://platform.claude.com/docs/en/about-claude/pricing'


class TokenBudgetExceeded(Exception):
    pass


class ProviderTokenBudget:
    def __init__(self, limit: int, *, max_cost_usd: float | None = None):
        if type(limit) is not int or limit <= 0:
            raise ValueError('token budget must be a positive integer')
        if max_cost_usd is not None and (not math.isfinite(max_cost_usd) or max_cost_usd <= 0):
            raise ValueError('USD budget must be positive and finite')
        self.limit, self.reserved = limit, 0
        self.cost_limit = None if max_cost_usd is None else int(max_cost_usd * 1_000_000)
        self.committed_cost = self.reported_cost = 0
        self.calls = []
        self.on_change = lambda: None
        self.exhausted = False

    def summary(self):
        return {'max_cost_usd': None if self.cost_limit is None else self.cost_limit / 1e6,
                'estimated_cost_usd': self.reported_cost / 1e6,
                'committed_cost_usd': self.committed_cost / 1e6,
                'reserved_tokens': self.reserved, 'pricing_source': PRICING_SOURCE,
                'pricing_verified': '2026-10-04', 'calls': self.calls,
                'scope': 'Research API tokens and web searches only; excludes preparation, taxes and hosting. Unknown charges retain their full reservation.'}

    async def create(self, client, *, reserve_input_tokens=0, reserve_output_tokens=0,
                     max_searches=0, stage='generation', **kwargs):
        rates = MODEL_PRICES.get(kwargs['model'])
        if self.cost_limit is not None and rates is None:
            raise ValueError('No verified price for model; refusing an unbudgeted call')
        input_rate, output_rate = rates or (0, 0)
        counted = await client.messages.count_tokens(**{
            key: value for key, value in kwargs.items()
            if key not in ('max_tokens', 'output_config')})
        # Web-search responses add unknown input. Their caller reserves a full
        # model context per allowed internal turn, not just the initial prompt.
        inputs = max(counted.input_tokens, reserve_input_tokens)
        outputs = max(kwargs['max_tokens'], reserve_output_tokens)
        reservation = inputs + outputs
        cost = inputs * input_rate + outputs * output_rate + max_searches * 10_000
        if self.reserved + reservation > self.limit or (
            self.cost_limit is not None and self.committed_cost + cost > self.cost_limit
        ):
            self.exhausted = True
            raise TokenBudgetExceeded('token budget or USD budget cannot cover this request')
        # Admission is atomic on the event loop: no await until both are reserved.
        self.reserved += reservation
        self.committed_cost += cost
        record = {'model': kwargs['model'], 'stage': stage, 'status': 'reserved',
                  'reserved_usd': cost / 1e6}
        self.calls.append(record)
        self.on_change()
        response = await client.messages.create(**kwargs)
        usage = getattr(response, 'usage', None)
        if usage is None:  # Unknown billing must never release reserved money.
            return response
        reported = TokenUsage(int(getattr(usage, 'input_tokens', 0)), int(getattr(usage, 'output_tokens', 0)))
        cache_write = int(getattr(usage, 'cache_creation_input_tokens', 0) or 0)
        cache_read = int(getattr(usage, 'cache_read_input_tokens', 0) or 0)
        searches = int(getattr(getattr(usage, 'server_tool_use', None), 'web_search_requests', 0) or 0)
        actual = (reported.input_tokens + cache_read + 2 * cache_write) * input_rate + reported.output_tokens * output_rate + searches * 10_000
        self.reserved += reported.total_tokens + cache_read + cache_write - reservation
        self.committed_cost += actual - cost
        self.reported_cost += actual
        record.update(status='reported', input_tokens=reported.input_tokens,
                      output_tokens=reported.output_tokens, searches=searches, estimated_usd=actual / 1e6)
        self.on_change()
        return response
