"""Unit tests for the PayGate request adapter and provider selection."""

from __future__ import annotations

import pytest
from conftest import make_case_file
from pydantic import ValidationError

from intenttrace.checks.integrity import check_integrity
from intenttrace.crypto import mandate_hash
from intenttrace.forensics.replay import original_choice
from intenttrace.paygate import (
    GateRequest,
    provider_from_env,
    request_to_case,
)

CONTENT = [
    {"item_id": "m1", "source": "merchant", "text": "desc", "product_id": "p-1"},
    {"item_id": "r1", "source": "review", "text": "great", "product_id": "p-1"},
    {"item_id": "q1", "source": "qa", "text": "does it fit?", "product_id": "p-1"},
    {"item_id": "h1", "source": "hidden", "text": "secret"},
    {"item_id": "e1", "source": "external_agent", "text": "hello"},
]


def _req(content=None, **over) -> GateRequest:
    case, _ = make_case_file()
    raw = {
        "public_keys": case.public_keys,
        "intent": case.intent.model_dump(),
        "cart": case.cart.model_dump(),
        "content": CONTENT if content is None else content,
        **over,
    }
    return GateRequest.model_validate(raw)


def test_placeholder_payment_and_constants():
    req = _req()
    case = request_to_case(req)
    assert case.case_id == "paygate-request"
    assert case.payment.cart_mandate_hash == mandate_hash(req.cart)
    assert case.payment.amount_cents == req.cart.total_cents
    assert case.payment.signer == "agent"
    assert case.payment.signature == ""
    assert case.listing_after is None and case.delivered is None
    assert case.listings_at_purchase == []


def test_trace_shape_and_source_mapping():
    req = _req()
    trace = request_to_case(req).trace
    assert [s.kind for s in trace] == ["instruction", *["observe"] * 5, "decide"]
    assert trace[0].source == "user"
    assert trace[0].content == req.intent.natural_language
    observed = {s.step_id: s.source for s in trace if s.kind == "observe"}
    assert observed == {
        "m1": "merchant",
        "r1": "review",
        "q1": "review",
        "h1": "external_agent",
        "e1": "external_agent",
    }
    assert trace[-1].product_id == req.cart.items[0].product_id
    assert original_choice(request_to_case(req)) == "p-1"


def test_default_item_ids_become_step_ids():
    case = request_to_case(_req(content=[{"source": "review", "text": "a"}]))
    assert [s.step_id for s in case.trace if s.kind == "observe"] == ["c0"]


def test_valid_signed_request_only_fails_payment_signature():
    failures = check_integrity(request_to_case(_req())).failures
    assert [(f.kind, f.field) for f in failures] == [("signature_invalid", "payment.signature")]


def test_tampered_cart_still_reports_cart_failures():
    req = _req()
    bad = req.model_copy(update={"cart": req.cart.model_copy(update={"total_cents": 1})})
    fields = {f.field for f in check_integrity(request_to_case(bad)).failures}
    assert "cart.signature" in fields and "cart.total_cents" in fields


def test_empty_cart_rejected():
    case, _ = make_case_file()
    cart = case.cart.model_dump() | {"items": []}
    with pytest.raises(ValidationError):
        GateRequest.model_validate(
            {"public_keys": case.public_keys, "intent": case.intent.model_dump(), "cart": cart}
        )


def test_duplicate_item_ids_rejected():
    dup = [{"item_id": "x", "source": "review", "text": "a"}] * 2
    with pytest.raises(ValidationError):
        _req(content=dup)


def test_provider_unset_empty_none(monkeypatch):
    monkeypatch.delenv("INTENTTRACE_LLM_PROVIDER", raising=False)
    assert provider_from_env() == (None, [])
    for value in ("", "  ", "none", "NONE"):
        monkeypatch.setenv("INTENTTRACE_LLM_PROVIDER", value)
        assert provider_from_env() == (None, [])


def test_provider_fake(monkeypatch):
    monkeypatch.setenv("INTENTTRACE_LLM_PROVIDER", "fake")
    provider, notes = provider_from_env()
    assert provider is not None and notes == []


def test_provider_unknown_or_unconfigured(monkeypatch):
    monkeypatch.setenv("INTENTTRACE_LLM_PROVIDER", "bogus")
    assert provider_from_env() == (None, ["llm_unavailable"])


def test_provider_factory_error_maps_to_note(monkeypatch):
    def boom(name):
        raise ValueError("missing key")

    monkeypatch.setattr("intenttrace.paygate.make_provider", boom)
    monkeypatch.setenv("INTENTTRACE_LLM_PROVIDER", "anthropic")
    assert provider_from_env() == (None, ["llm_unavailable"])
