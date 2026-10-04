"""Bounded Anthropic adapter for executable evolutionary candidates."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import anthropic
from .budget import ProviderTokenBudget, TokenBudgetExceeded

from the_pigeon_holes.evolution.models import (
    CandidateDraft,
    GenerationRequest,
    GenerationResult,
    TokenUsage,
)

_SUBMIT_CANDIDATE_TOOL = {
    "name": "submit_candidate",
    "description": (
        "Submit exactly one evolutionary program candidate. The hypothesis, predicted "
        "effect, falsification condition, mechanism tags, and complete Python source "
        "must describe the same implementation. The source must implement the exact "
        "solve signature in the request and must not contain evaluator or benchmark data."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "hypothesis": {"type": "string"},
            "predicted_effect": {"type": "string"},
            "falsification_condition": {"type": "string"},
            "mechanism_tags": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "maxItems": 12,
            },
            "source_code": {"type": "string"},
        },
        "required": [
            "hypothesis",
            "predicted_effect",
            "falsification_condition",
            "mechanism_tags",
            "source_code",
        ],
        "additionalProperties": False,
    },
}


@dataclass(frozen=True)
class AnthropicGeneratorConfig:
    model: str
    token_budget: int | None = None
    max_output_tokens: int = 4_096
    max_concurrency: int = 4
    timeout_seconds: float = 90.0
    max_attempts: int = 3
    retry_backoff_seconds: float = 0.5

    def __post_init__(self) -> None:
        if not isinstance(self.model, str) or not self.model.strip():
            raise ValueError("model cannot be empty")
        if self.token_budget is not None and (type(self.token_budget) is not int or self.token_budget <= 0):
            raise ValueError("token_budget must be a positive integer")
        for name in ("max_output_tokens", "max_concurrency", "max_attempts"):
            if type(getattr(self, name)) is not int or getattr(self, name) <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive and finite")
        if (
            not math.isfinite(self.retry_backoff_seconds)
            or self.retry_backoff_seconds < 0
        ):
            raise ValueError("retry_backoff_seconds must be finite and nonnegative")


class AnthropicProgramGenerator:
    """Generate one structured candidate per backend-authored request."""

    def __init__(
        self,
        config: AnthropicGeneratorConfig,
        *,
        client: Any | None = None,
        budget: ProviderTokenBudget | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.config = config
        self.client = client or anthropic.AsyncAnthropic(max_retries=0)
        self._sleep = sleep
        self.budget = budget or (ProviderTokenBudget(config.token_budget) if config.token_budget is not None else None)
        self._semaphore = asyncio.Semaphore(config.max_concurrency)

    async def generate(
        self,
        requests: Sequence[GenerationRequest],
    ) -> Sequence[GenerationResult]:
        """Generate a stable-order batch while bounding provider concurrency."""
        return tuple(await asyncio.gather(*(self._generate_one(request) for request in requests)))

    async def _generate_one(self, request: GenerationRequest) -> GenerationResult:
        usage = TokenUsage()
        last_error = "generation failed"
        async with self._semaphore:
            for attempt in range(1, self.config.max_attempts + 1):
                try:
                    response = await self._create(
                        model=self.config.model,
                        max_tokens=self.config.max_output_tokens,
                        timeout=self.config.timeout_seconds,
                        system=(
                            "You are a semantic variation operator for mathematical "
                            "algorithm search. Follow the fixed problem contract and submit "
                            "exactly one internally consistent candidate."
                        ),
                        messages=[{"role": "user", "content": request.prompt}],
                        tools=[_SUBMIT_CANDIDATE_TOOL],
                        tool_choice={
                            "type": "tool",
                            "name": "submit_candidate",
                            "disable_parallel_tool_use": True,
                        },
                    )
                except TokenBudgetExceeded:
                    last_error = "remaining token budget cannot cover the counted prompt and maximum output"
                    break
                except anthropic.APIError as exc:
                    last_error = self._provider_error(exc)
                    if attempt == self.config.max_attempts or not self._retryable(exc):
                        break
                else:
                    usage = self._add_usage(usage, response)
                    try:
                        return GenerationResult(
                            request_id=request.id,
                            usage=usage,
                            draft=self._parse_candidate(response),
                        )
                    except (TypeError, ValueError) as exc:
                        last_error = f"invalid structured candidate: {exc}"
                        if attempt == self.config.max_attempts:
                            break

                await self._sleep(
                    self.config.retry_backoff_seconds * (2 ** (attempt - 1))
                )

        return GenerationResult(request_id=request.id, usage=usage, error=last_error)

    async def aclose(self):
        await self.client.close()

    async def _create(self, **kwargs):
        if self.budget is None:
            return await self.client.messages.create(**kwargs)
        return await self.budget.create(self.client, **kwargs)

    @staticmethod
    def _parse_candidate(response: Any) -> CandidateDraft:
        if getattr(response, "stop_reason", None) == "max_tokens":
            raise ValueError("provider output reached max_tokens before submission")
        blocks = [
            block
            for block in getattr(response, "content", ())
            if getattr(block, "type", None) == "tool_use"
            and getattr(block, "name", None) == "submit_candidate"
        ]
        if len(blocks) != 1:
            raise ValueError("response must contain exactly one submit_candidate tool call")
        data = getattr(blocks[0], "input", None)
        if not isinstance(data, Mapping):
            raise ValueError("submit_candidate input must be an object")
        tags = data.get("mechanism_tags")
        if (
            not isinstance(tags, list)
            or not 1 <= len(tags) <= 12
            or not all(isinstance(tag, str) and tag.strip() for tag in tags)
        ):
            raise ValueError("mechanism_tags must contain 1 to 12 nonempty strings")
        text_fields = (
            "hypothesis",
            "predicted_effect",
            "falsification_condition",
            "source_code",
        )
        for field in text_fields:
            if field not in data:
                raise ValueError(f"missing field {field!r}")
            if not isinstance(data[field], str):
                raise ValueError(f"{field} must be a string")
        return CandidateDraft(
            hypothesis=data["hypothesis"],
            predicted_effect=data["predicted_effect"],
            falsification_condition=data["falsification_condition"],
            mechanism_tags=tuple(tags),
            source_code=data["source_code"],
        )

    @staticmethod
    def _add_usage(current: TokenUsage, response: Any) -> TokenUsage:
        reported = getattr(response, "usage", None)
        return TokenUsage(
            input_tokens=current.input_tokens + int(getattr(reported, "input_tokens", 0)),
            output_tokens=current.output_tokens + int(getattr(reported, "output_tokens", 0)),
        )

    @staticmethod
    def _retryable(error: anthropic.APIError) -> bool:
        if isinstance(error, anthropic.APIConnectionError):
            return True
        return isinstance(error, anthropic.APIStatusError) and (
            error.status_code in (408, 409, 425, 429) or error.status_code >= 500
        )

    @staticmethod
    def _provider_error(error: anthropic.APIError) -> str:
        if isinstance(error, anthropic.APIStatusError):
            return f"provider {type(error).__name__} (HTTP {error.status_code})"
        return f"provider {type(error).__name__}"
