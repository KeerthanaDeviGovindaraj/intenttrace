"""Tests for checks/integrity.py: a passing and failing case for every check in design section 3.

Failing cases rebuild the hash chain and re-sign so that only the targeted check fails.
"""

from __future__ import annotations

from intenttrace.checks.integrity import check_integrity
from intenttrace.crypto import generate_keypair, mandate_hash, sign


def _kinds(result):
    return [f.kind for f in result.failures]


def _fields(result):
    return [f.field for f in result.failures]


def _resign(model, key, **updates):
    model = model.model_copy(update={**updates, "signature": ""})
    return model.model_copy(update={"signature": sign(model, key)})


def _rebuild(case, keys, intent=None, cart=None, payment=None, cart_key=None, payment_key=None):
    """Return a case with a consistent hash chain; downstream mandates are re-signed."""
    intent = intent or case.intent
    cart = _resign(
        cart or case.cart,
        cart_key or keys[(cart or case.cart).signer],
        intent_mandate_hash=mandate_hash(intent),
    )
    payment = _resign(
        payment or case.payment,
        payment_key or keys[(payment or case.payment).signer],
        cart_mandate_hash=mandate_hash(cart),
    )
    return case.model_copy(update={"intent": intent, "cart": cart, "payment": payment})


# --- all checks pass ---


def test_valid_case_passes(signed_case):
    case, _ = signed_case
    result = check_integrity(case)
    assert result.ok and result.failures == []


# --- intent signature ---


def test_intent_signature_fails_with_wrong_key(signed_case):
    case, keys = signed_case
    intent = _resign(case.intent, keys["agent"])
    result = check_integrity(_rebuild(case, keys, intent=intent))
    assert _fields(result) == ["intent.signature"]
    assert _kinds(result) == ["signature_invalid"]


def test_intent_tamper_breaks_signature_and_hash(signed_case):
    case, _ = signed_case
    bad = case.model_copy(update={"intent": case.intent.model_copy(update={"natural_language": "x"})})
    kinds = _kinds(check_integrity(bad))
    assert "signature_invalid" in kinds and "hash_mismatch" in kinds


# --- cart signature (agent signer key) ---


def test_cart_signature_verified_with_agent_key(signed_case):
    case, _ = signed_case
    assert case.cart.signer == "agent"
    assert check_integrity(case).ok


def test_cart_signature_fails_when_signed_with_wrong_key(signed_case):
    case, keys = signed_case
    # Cart claims the agent signer but is signed with the user's key.
    result = check_integrity(_rebuild(case, keys, cart_key=keys["user"]))
    assert _fields(result) == ["cart.signature"]
    assert _kinds(result) == ["signature_invalid"]


def test_cart_signature_fails_when_signer_key_missing(signed_case):
    case, _ = signed_case
    keys_without_agent = {"user": case.public_keys["user"]}
    result = check_integrity(case.model_copy(update={"public_keys": keys_without_agent}))
    assert "cart.signature" in _fields(result)
    assert "payment.signature" in _fields(result)
    assert set(_kinds(result)) == {"signature_invalid"}


# --- payment signature ---


def test_payment_signature_fails_with_wrong_key(signed_case):
    case, keys = signed_case
    result = check_integrity(_rebuild(case, keys, payment_key=keys["user"]))
    assert _fields(result) == ["payment.signature"]
    assert _kinds(result) == ["signature_invalid"]


def test_payment_signature_fails_with_unknown_key(signed_case):
    case, keys = signed_case
    other_priv, _ = generate_keypair()
    result = check_integrity(_rebuild(case, keys, payment_key=other_priv))
    assert _fields(result) == ["payment.signature"]


# --- cart.intent_mandate_hash ---


def test_cart_intent_hash_fails_when_wrong(signed_case):
    case, keys = signed_case
    cart = _resign(case.cart, keys["agent"], intent_mandate_hash="0" * 64)
    payment = _resign(case.payment, keys["agent"], cart_mandate_hash=mandate_hash(cart))
    result = check_integrity(case.model_copy(update={"cart": cart, "payment": payment}))
    assert _fields(result) == ["cart.intent_mandate_hash"]
    assert _kinds(result) == ["hash_mismatch"]
    assert result.failures[0].actual == "0" * 64


# --- payment.cart_mandate_hash ---


def test_payment_cart_hash_fails_when_wrong(signed_case):
    case, keys = signed_case
    payment = _resign(case.payment, keys["agent"], cart_mandate_hash="f" * 64)
    result = check_integrity(case.model_copy(update={"payment": payment}))
    assert _fields(result) == ["payment.cart_mandate_hash"]
    assert _kinds(result) == ["hash_mismatch"]


# --- payment.amount == cart.total ---


def test_amount_mismatch_fails(signed_case):
    case, keys = signed_case
    payment = _resign(case.payment, keys["agent"], amount_cents=1)
    result = check_integrity(case.model_copy(update={"payment": payment}))
    assert _fields(result) == ["payment.amount_cents"]
    assert _kinds(result) == ["amount_mismatch"]
    f = result.failures[0]
    assert (f.expected, f.actual) == (4000, 1)


def test_tampered_payment_amount_breaks_signature_too(signed_case):
    case, _ = signed_case
    bad = case.model_copy(update={"payment": case.payment.model_copy(update={"amount_cents": 1})})
    kinds = _kinds(check_integrity(bad))
    assert "signature_invalid" in kinds and "amount_mismatch" in kinds


# --- cart.total == sum(unit * qty) ---


def test_total_mismatch_fails(signed_case):
    case, keys = signed_case
    cart = _resign(case.cart, keys["agent"], total_cents=9999)
    payment = _resign(case.payment, keys["agent"], cart_mandate_hash=mandate_hash(cart), amount_cents=9999)
    result = check_integrity(case.model_copy(update={"cart": cart, "payment": payment}))
    assert _kinds(result) == ["total_mismatch"]
    f = result.failures[0]
    assert (f.expected, f.actual) == (4000, 9999)


def test_total_matches_with_multiple_quantities(signed_case):
    case, keys = signed_case
    item = case.cart.items[0].model_copy(update={"quantity": 3})
    cart = _resign(case.cart, keys["agent"], items=[item], total_cents=12000)
    payment = _resign(case.payment, keys["agent"], cart_mandate_hash=mandate_hash(cart), amount_cents=12000)
    assert check_integrity(case.model_copy(update={"cart": cart, "payment": payment})).ok


# --- human_present => user-signed cart ---


def _human_present_case(case, keys, human_present, cart_signer):
    intent = _resign(case.intent, keys["user"], human_present=human_present)
    cart = case.cart.model_copy(update={"signer": cart_signer})
    return _rebuild(case, keys, intent=intent, cart=cart)


def test_human_present_with_agent_signed_cart_fails(signed_case):
    case, keys = signed_case
    result = check_integrity(_human_present_case(case, keys, True, "agent"))
    assert _kinds(result) == ["signer_violation"]
    assert _fields(result) == ["cart.signer"]


def test_human_present_with_user_signed_cart_passes(signed_case):
    case, keys = signed_case
    assert check_integrity(_human_present_case(case, keys, True, "user")).ok


def test_human_not_present_allows_agent_signed_cart(signed_case):
    case, keys = signed_case
    assert check_integrity(_human_present_case(case, keys, False, "agent")).ok
