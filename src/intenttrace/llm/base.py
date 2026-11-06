"""LLM provider protocol, usage tracking and the validate-and-retry helper (design.md section 10)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol, TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    """A provider failed or returned output that could not be parsed."""


class LLMUnavailable(Exception):
    """Raised by ``call_validated`` after the retry is exhausted; stages degrade on this."""


@dataclass
class Usage:
    """Cumulative usage for one provider instance."""

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latencies_s: list[float] = field(default_factory=list)

    def record(
        self, input_tokens: int, output_tokens: int, latency_s: float = 0.0, cost_usd: float = 0.0
    ) -> None:
        self.calls += 1
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.cost_usd += cost_usd
        self.latencies_s.append(latency_s)


class LLMProvider(Protocol):
    """Returns an instance of ``schema`` or raises ``LLMError`` / pydantic ``ValidationError``."""

    name: str
    model: str
    usage: Usage

    def complete_json(self, system: str, user: str, schema: type[T]) -> T: ...


def call_validated(
    provider: LLMProvider,
    system: str,
    user: str,
    schema: type[T],
    check: Callable[[T], None] | None = None,
) -> T:
    """Call the provider, validate against ``schema`` (and ``check``), retry once, then give up.

    ``check`` may raise ``ValueError`` for semantic problems (for example out-of-range offsets).
    """
    last: Exception | None = None
    for _ in range(2):
        try:
            result = provider.complete_json(system, user, schema)
            if not isinstance(result, schema):
                result = schema.model_validate(result)
            if check is not None:
                check(result)
            return result
        except (LLMError, ValidationError, ValueError) as exc:
            last = exc
    raise LLMUnavailable(str(last))
