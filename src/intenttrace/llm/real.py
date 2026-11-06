"""Real LLM providers (Anthropic, OpenAI) behind the ``LLMProvider`` protocol (design.md section 10).

Configuration comes from the environment: ``INTENTTRACE_LLM_PROVIDER`` picks the provider,
``INTENTTRACE_LLM_MODEL`` overrides the model, and each provider reads its own API key variable
(``ANTHROPIC_API_KEY`` / ``OPENAI_API_KEY``). The SDK is imported lazily, and a client can be injected,
so tests need neither network nor keys.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any

from pydantic import ValidationError

from intenttrace.llm.base import LLMError, T, Usage

# Estimated USD per million (input, output) tokens. Estimates only; unknown models cost 0 and are flagged
# by ``price_known``. Update when provider pricing changes.
PRICES_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-sonnet-4-5": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "gpt-4o": (2.5, 10.0),
    "gpt-4o-mini": (0.15, 0.6),
}

DEFAULT_MODELS = {"anthropic": "claude-sonnet-4-5", "openai": "gpt-4o-mini"}
API_KEY_VARS = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}
MAX_OUTPUT_TOKENS = 1024
_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    prices = PRICES_PER_MTOK.get(model)
    if prices is None:
        # Match dated snapshots such as "claude-sonnet-4-5-20250929" by longest known prefix.
        known = [m for m in PRICES_PER_MTOK if model.startswith(m)]
        if not known:
            return 0.0
        prices = PRICES_PER_MTOK[max(known, key=len)]
    return (input_tokens * prices[0] + output_tokens * prices[1]) / 1_000_000


def _parse(text: str, schema: type[T]) -> T:
    text = text.strip()
    fenced = _FENCE.match(text)
    if fenced:
        text = fenced.group(1)
    return schema.model_validate(json.loads(text))


class _JSONProvider:
    """Shared flow: build the prompt, call the SDK, validate, retry once on invalid JSON."""

    name = ""

    def __init__(self, model: str, client: Any = None, api_key: str | None = None):
        self.model = model
        self.usage = Usage()
        self._client = client if client is not None else self._build_client(api_key)

    # -- provider specific ------------------------------------------------------------------------------
    def _build_client(self, api_key: str | None) -> Any:  # pragma: no cover - overridden
        raise NotImplementedError

    def _request(self, system: str, messages: list[dict[str, str]]) -> tuple[str, int, int]:
        """Return (text, input_tokens, output_tokens)."""
        raise NotImplementedError

    # -- shared -----------------------------------------------------------------------------------------
    def complete_json(self, system: str, user: str, schema: type[T]) -> T:
        full_system = (
            f"{system}\n\nRespond with a single JSON object and nothing else. "
            f"It must match this JSON Schema:\n{json.dumps(schema.model_json_schema())}"
        )
        messages = [{"role": "user", "content": user}]
        last: Exception | None = None
        for attempt in range(2):
            text = self._timed_request(full_system, messages)
            try:
                return _parse(text, schema)
            except (json.JSONDecodeError, ValidationError) as exc:
                last = exc
                if attempt == 0:
                    messages = [
                        *messages,
                        {"role": "assistant", "content": text},
                        {
                            "role": "user",
                            "content": f"That was not valid for the schema ({type(exc).__name__}). "
                            "Reply again with only the corrected JSON object.",
                        },
                    ]
        raise LLMError(f"{self.name} returned invalid JSON after one retry: {last}")

    def _timed_request(self, system: str, messages: list[dict[str, str]]) -> str:
        start = time.perf_counter()
        try:
            text, tokens_in, tokens_out = self._request(system, messages)
        except Exception as exc:  # SDK errors vary by version; surface one error type to callers.
            self.usage.record(0, 0, time.perf_counter() - start)
            raise LLMError(f"{self.name} request failed: {type(exc).__name__}: {exc}") from exc
        self.usage.record(
            tokens_in,
            tokens_out,
            time.perf_counter() - start,
            estimate_cost(self.model, tokens_in, tokens_out),
        )
        return text


class AnthropicProvider(_JSONProvider):
    name = "anthropic"

    def _build_client(self, api_key: str | None) -> Any:
        try:
            import anthropic
        except ImportError as exc:
            raise ValueError("anthropic is not installed (pip install 'intenttrace[llm]')") from exc
        return anthropic.Anthropic(api_key=api_key)

    def _request(self, system: str, messages: list[dict[str, str]]) -> tuple[str, int, int]:
        resp = self._client.messages.create(
            model=self.model,
            system=system,
            messages=messages,
            max_tokens=MAX_OUTPUT_TOKENS,
            temperature=0,
        )
        text = "".join(getattr(b, "text", "") for b in resp.content)
        return text, int(resp.usage.input_tokens), int(resp.usage.output_tokens)


class OpenAIProvider(_JSONProvider):
    name = "openai"

    def _build_client(self, api_key: str | None) -> Any:
        try:
            import openai
        except ImportError as exc:
            raise ValueError("openai is not installed (pip install 'intenttrace[llm]')") from exc
        return openai.OpenAI(api_key=api_key)

    def _request(self, system: str, messages: list[dict[str, str]]) -> tuple[str, int, int]:
        resp = self._client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": system}, *messages],
            max_tokens=MAX_OUTPUT_TOKENS,
            temperature=0,
            response_format={"type": "json_object"},
        )
        usage = resp.usage
        return (
            resp.choices[0].message.content or "",
            int(usage.prompt_tokens) if usage else 0,
            int(usage.completion_tokens) if usage else 0,
        )


_PROVIDERS = {"anthropic": AnthropicProvider, "openai": OpenAIProvider}


def make_real_provider(name: str, client: Any = None) -> _JSONProvider:
    """Build a real provider; raises ``ValueError`` for unknown names or a missing API key."""
    cls = _PROVIDERS.get(name)
    if cls is None:
        raise ValueError(f"Unsupported provider: {name!r}")
    model = os.environ.get("INTENTTRACE_LLM_MODEL", "").strip() or DEFAULT_MODELS[name]
    api_key = None
    if client is None:
        var = API_KEY_VARS[name]
        api_key = os.environ.get(var, "").strip()
        if not api_key:
            raise ValueError(f"{var} is not set (required for provider {name!r})")
    return cls(model, client=client, api_key=api_key)
