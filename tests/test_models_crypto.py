"""Tests for models.py, crypto.py and schema export (requirements 1.1-1.5, 2.1)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from conftest import make_case_file
from pydantic import ValidationError

from intenttrace.crypto import canonical, generate_keypair, mandate_hash, sign, verify
from intenttrace.models import CaseFile, Constraint, IntentMandate, PaymentMandate, TraceStep

ROOT = Path(__file__).resolve().parent.parent
LUHN = "4242424242424242"  # Luhn-valid


def _signer_key(case: CaseFile, name: str) -> str:
    return case.public_keys[getattr(case, name).signer]


@pytest.mark.parametrize("name", ["intent", "cart", "payment"])
def test_round_trip(signed_case, name):
    case, _ = signed_case
    assert verify(getattr(case, name), _signer_key(case, name))


@pytest.mark.parametrize(
    ("name", "field", "value"),
    [
        ("intent", "natural_language", "Buy anything"),
        ("intent", "user_id", "evil"),
        ("intent", "human_present", True),
        ("intent", "created_at", "2030-01-01T00:00:00Z"),
        ("intent", "constraints", Constraint(max_total_cents=999999)),
        ("cart", "total_cents", 1),
        ("cart", "merchant_id", "other"),
        ("cart", "intent_mandate_hash", "0" * 64),
        ("cart", "items", []),
        ("cart", "signer", "user"),
        ("payment", "amount_cents", 1),
        ("payment", "payment_method_token", "tok_sim_other"),
        ("payment", "agent_involved", False),
        ("payment", "cart_mandate_hash", "f" * 64),
    ],
)
def test_tamper_detected(signed_case, name, field, value):
    case, _ = signed_case
    m = getattr(case, name)
    tampered = m.model_copy(update={field: value})
    assert verify(m, _signer_key(case, name))
    assert not verify(tampered, _signer_key(case, name))


@pytest.mark.parametrize("name", ["intent", "cart", "payment"])
def test_wrong_key_fails(signed_case, name):
    case, _ = signed_case
    _, other_pub = generate_keypair()
    assert not verify(getattr(case, name), other_pub)


def test_garbage_does_not_raise(signed_case):
    case, _ = signed_case
    good_key = case.public_keys["user"]
    assert verify(case.intent.model_copy(update={"signature": "!!notbase64"}), good_key) is False
    assert verify(case.intent.model_copy(update={"signature": ""}), good_key) is False
    assert verify(case.intent, "garbage") is False
    assert verify(case.intent, "") is False
    assert verify(case.intent, "AAAA") is False


def test_mandate_hash_changes(signed_case):
    case, _ = signed_case
    h = mandate_hash(case.payment)
    assert h == mandate_hash(case.payment)
    assert mandate_hash(case.payment.model_copy(update={"signature": "x"})) != h
    assert mandate_hash(case.payment.model_copy(update={"amount_cents": 1})) != h


def test_canonical_deterministic_and_order_independent():
    a = {"b": 1, "a": {"y": [1, 2], "x": "é"}}
    b = {"a": {"x": "é", "y": [1, 2]}, "b": 1}
    assert canonical(a) == canonical(b) == canonical(a)
    assert canonical(a) == '{"a":{"x":"é","y":[1,2]},"b":1}'.encode()


def test_hash_chain_valid(signed_case):
    case, _ = signed_case
    assert case.cart.intent_mandate_hash == mandate_hash(case.intent)
    assert case.payment.cart_mandate_hash == mandate_hash(case.cart)


def test_sign_helper_uses_signing_key():
    priv, pub = generate_keypair()
    case, _ = make_case_file()
    sig = sign(case.intent, priv)
    assert verify(case.intent.model_copy(update={"signature": sig}), pub)


@pytest.mark.parametrize(
    "number",
    [LUHN, "4242 4242 4242 4242", "4242-4242-4242-4242"],
)
def test_card_number_rejected(signed_case, number):
    case, _ = signed_case
    with pytest.raises(ValidationError):
        TraceStep(step_id="s", kind="think", source="agent", content=f"card {number} ok", timestamp="t")
    with pytest.raises(ValidationError):
        IntentMandate(**{**case.intent.model_dump(), "natural_language": number})
    with pytest.raises(ValidationError):
        CaseFile(**{**case.model_dump(), "case_id": number})


def test_non_luhn_digits_accepted():
    step = TraceStep(
        step_id="s", kind="think", source="agent", content="order 4242424242424241", timestamp="t"
    )
    assert "4242424242424241" in step.content


def test_exempt_fields_accepted(signed_case):
    case, _ = signed_case
    data = case.model_dump()
    data["cart"]["intent_mandate_hash"] = LUHN + "abcdef"
    data["cart"]["signature"] = LUHN
    data["public_keys"]["user"] = LUHN
    CaseFile(**data)


def test_payment_token_accepted(signed_case):
    case, _ = signed_case
    assert case.payment.payment_method_token == "tok_sim_abc"
    with pytest.raises(ValidationError):
        PaymentMandate(**{**case.payment.model_dump(), "payment_method_token": LUHN})


def test_extra_fields_forbidden(signed_case):
    case, _ = signed_case
    with pytest.raises(ValidationError):
        CaseFile(**{**case.model_dump(), "bogus": 1})
    with pytest.raises(ValidationError):
        IntentMandate(**{**case.intent.model_dump(), "bogus": 1})


def test_optional_fields_absent_valid(signed_case):
    case, _ = signed_case
    data = case.model_dump()
    for k in ("agent_config", "listing_after", "delivered"):
        data.pop(k, None)
    c = CaseFile(**data)
    assert c.agent_config is None and c.listing_after is None and c.delivered is None


def test_schema_export_matches_committed(tmp_path):
    spec = importlib.util.spec_from_file_location("export_schema", ROOT / "scripts" / "export_schema.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    out = mod.export_schema(tmp_path / "schema.json")
    generated = json.loads(out.read_text(encoding="utf-8"))
    committed = json.loads((ROOT / "docs" / "case-file.schema.json").read_text(encoding="utf-8"))
    assert generated == committed
