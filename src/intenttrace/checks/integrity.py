"""Stage 1: integrity checks (design.md section 3). Deterministic, never calls an LLM."""

from __future__ import annotations

from pydantic import BaseModel, Field

from intenttrace.crypto import mandate_hash, verify
from intenttrace.models import CaseFile, Finding


class IntegrityResult(BaseModel):
    ok: bool
    failures: list[Finding] = Field(default_factory=list)


def _signature_check(name: str, model, signer: str, case: CaseFile) -> Finding | None:
    key = case.public_keys.get(signer)
    if key is None:
        return Finding(
            kind="signature_invalid",
            detail=f"No public key for signer '{signer}' to verify the {name} mandate.",
            field=f"{name}.signature",
            expected=f"public key for {signer}",
            actual=None,
            method="deterministic",
        )
    if not verify(model, key):
        return Finding(
            kind="signature_invalid",
            detail=f"The {name} mandate signature does not verify against the {signer} key.",
            field=f"{name}.signature",
            expected=f"valid {signer} signature",
            actual="invalid",
            method="deterministic",
        )
    return None


def check_integrity(case: CaseFile) -> IntegrityResult:
    """Run all integrity checks in design order and collect every failure."""
    failures: list[Finding] = []
    intent, cart, payment = case.intent, case.cart, case.payment

    for name, model, signer in (
        ("intent", intent, "user"),
        ("cart", cart, cart.signer),
        ("payment", payment, payment.signer),
    ):
        f = _signature_check(name, model, signer, case)
        if f:
            failures.append(f)

    expected_intent_hash = mandate_hash(intent)
    if cart.intent_mandate_hash != expected_intent_hash:
        failures.append(
            Finding(
                kind="hash_mismatch",
                detail="cart.intent_mandate_hash does not match the intent mandate.",
                field="cart.intent_mandate_hash",
                expected=expected_intent_hash,
                actual=cart.intent_mandate_hash,
                method="deterministic",
            )
        )

    expected_cart_hash = mandate_hash(cart)
    if payment.cart_mandate_hash != expected_cart_hash:
        failures.append(
            Finding(
                kind="hash_mismatch",
                detail="payment.cart_mandate_hash does not match the cart mandate.",
                field="payment.cart_mandate_hash",
                expected=expected_cart_hash,
                actual=payment.cart_mandate_hash,
                method="deterministic",
            )
        )

    if payment.amount_cents != cart.total_cents:
        failures.append(
            Finding(
                kind="amount_mismatch",
                detail="payment.amount_cents differs from cart.total_cents.",
                field="payment.amount_cents",
                expected=cart.total_cents,
                actual=payment.amount_cents,
                method="deterministic",
            )
        )

    items_total = sum(i.unit_price_cents * i.quantity for i in cart.items)
    if cart.total_cents != items_total:
        failures.append(
            Finding(
                kind="total_mismatch",
                detail="cart.total_cents differs from the sum of unit_price * quantity.",
                field="cart.total_cents",
                expected=items_total,
                actual=cart.total_cents,
                method="deterministic",
            )
        )

    if intent.human_present and cart.signer != "user":
        failures.append(
            Finding(
                kind="signer_violation",
                detail="Intent requires a human present, but the cart was not signed by the user.",
                field="cart.signer",
                expected="user",
                actual=cart.signer,
                method="deterministic",
            )
        )

    return IntegrityResult(ok=not failures, failures=failures)
