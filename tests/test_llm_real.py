"""Real providers with a mocked SDK client: no network, no keys."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from intenttrace.llm.base import LLMError, call_validated
from intenttrace.llm.factory import make_provider
from intenttrace.llm.prompts import ClassifyResult
from intenttrace.llm.real import AnthropicProvider, OpenAIProvider, estimate_cost

GOOD = '{"suspicious": true, "spans": [{"start": 0, "end": 4, "reason": "x"}]}'


class FakeAnthropicClient:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return SimpleNamespace(
            content=[SimpleNamespace(text=reply)], usage=SimpleNamespace(input_tokens=100, output_tokens=20)
        )


class FakeOpenAIClient:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        message = SimpleNamespace(content=self.replies.pop(0))
        return SimpleNamespace(
            choices=[SimpleNamespace(message=message)],
            usage=SimpleNamespace(prompt_tokens=50, completion_tokens=10),
        )


def test_anthropic_parses_json_and_tracks_usage():
    client = FakeAnthropicClient([GOOD])
    p = AnthropicProvider("claude-sonnet-4-5", client=client)
    result = p.complete_json("sys", "user", ClassifyResult)
    assert result.suspicious and result.spans[0].end == 4
    assert (p.usage.calls, p.usage.input_tokens, p.usage.output_tokens) == (1, 100, 20)
    assert p.usage.cost_usd == pytest.approx(0.0006)
    assert len(p.usage.latencies_s) == 1
    assert "JSON Schema" in client.calls[0]["system"]


def test_invalid_json_is_retried_once_then_succeeds():
    client = FakeAnthropicClient(["not json at all", f"```json\n{GOOD}\n```"])
    p = AnthropicProvider("claude-haiku-4-5", client=client)
    assert p.complete_json("s", "u", ClassifyResult).suspicious
    assert p.usage.calls == 2
    assert client.calls[1]["messages"][-1]["role"] == "user"


def test_schema_violation_twice_raises_llm_error():
    client = FakeAnthropicClient(['{"suspicious": "maybe"}', "{}"])
    p = AnthropicProvider("claude-sonnet-4-5", client=client)
    with pytest.raises(LLMError):
        p.complete_json("s", "u", ClassifyResult)
    assert p.usage.calls == 2


def test_sdk_error_becomes_llm_error_and_is_counted():
    p = AnthropicProvider("claude-sonnet-4-5", client=FakeAnthropicClient([RuntimeError("boom")]))
    with pytest.raises(LLMError):
        p.complete_json("s", "u", ClassifyResult)
    assert p.usage.calls == 1


def test_openai_provider_works_with_call_validated():
    client = FakeOpenAIClient([GOOD])
    p = OpenAIProvider("gpt-4o-mini", client=client)
    assert call_validated(p, "s", "u", ClassifyResult).suspicious
    assert p.usage.input_tokens == 50 and p.usage.output_tokens == 10
    assert client.calls[0]["messages"][0]["role"] == "system"


def test_unknown_model_costs_zero_and_dated_snapshot_matches_prefix():
    assert estimate_cost("mystery", 1000, 1000) == 0.0
    assert estimate_cost("claude-sonnet-4-5-20250929", 1_000_000, 0) == 3.0


def test_factory_reads_env(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        make_provider("openai")
    with pytest.raises(ValueError, match="Unsupported"):
        make_provider("nonesuch")
    assert make_provider("fake").name == "fake"


def test_factory_builds_real_provider_with_model_override(monkeypatch):
    pytest.importorskip("anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setenv("INTENTTRACE_LLM_MODEL", "claude-haiku-4-5")
    p = make_provider("anthropic")
    assert (p.name, p.model) == ("anthropic", "claude-haiku-4-5")


def test_cli_provider_flag_without_key_exits_2(monkeypatch, tmp_path):
    from typer.testing import CliRunner

    from intenttrace.cli import app

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = CliRunner().invoke(app, ["bench", "--provider", "anthropic", "--n", "6", "--out", str(tmp_path)])
    assert result.exit_code == 2
