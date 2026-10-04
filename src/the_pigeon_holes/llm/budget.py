"""Shared conservative token admission for generator and advisory critic calls."""
from the_pigeon_holes.evolution.models import TokenUsage


class TokenBudgetExceeded(Exception):
    pass


class ProviderTokenBudget:
    def __init__(self, limit: int):
        if type(limit) is not int or limit <= 0:
            raise ValueError('token budget must be a positive integer')
        self.limit = limit
        self.reserved = 0

    async def create(self, client, **kwargs):
        counted = await client.messages.count_tokens(**{
            key: value for key, value in kwargs.items() if key != 'max_tokens'})
        reservation = counted.input_tokens + kwargs['max_tokens']
        if self.reserved + reservation > self.limit:
            raise TokenBudgetExceeded()
        # No await between admission and reservation; all adapters share this instance.
        self.reserved += reservation
        # Keep the reservation when billing is unknown after failure or cancellation.
        response = await client.messages.create(**kwargs)
        usage = getattr(response, 'usage', None)
        reported = TokenUsage(int(getattr(usage, 'input_tokens', 0)), int(getattr(usage, 'output_tokens', 0)))
        self.reserved += reported.total_tokens - reservation
        return response
