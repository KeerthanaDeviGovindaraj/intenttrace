"""Provider factory shared by the CLI, API, MCP server and benchmark."""

from __future__ import annotations

from intenttrace.llm.base import LLMProvider

AVAILABLE = ("fake", "anthropic", "openai")


def make_provider(name: str) -> LLMProvider:
    """Build a provider by name; raises ``ValueError`` for unknown names or missing configuration."""
    name = name.strip().lower()
    if name == "fake":
        from intenttrace.llm.fake import FakeProvider

        return FakeProvider()
    if name in ("anthropic", "openai"):
        from intenttrace.llm.real import make_real_provider

        return make_real_provider(name)
    raise ValueError(f"Unsupported provider: {name!r} (available: {', '.join(AVAILABLE)})")
