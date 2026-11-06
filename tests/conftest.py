"""Shared fixtures: a signed, valid CaseFile with generated keypairs and a correct hash chain."""

from __future__ import annotations

import pytest

from intenttrace.crypto import generate_keypair, mandate_hash, sign
from intenttrace.models import (
    CartItem,
    CartMandate,
    CaseFile,
    Constraint,
    DeliveredItem,
    IntentMandate,
    ListingSnapshot,
    PaymentMandate,
    TraceStep,
)

T0 = "2025-01-01T00:00:00Z"


def make_case_file() -> tuple[CaseFile, dict[str, str]]:
    """Return (signed CaseFile, {"user": priv, "agent": priv} keys dict of private keys)."""
    user_priv, user_pub = generate_keypair()
    agent_priv, agent_pub = generate_keypair()

    intent = IntentMandate(
        mandate_id="intent-1",
        user_id="user-1",
        natural_language="Buy a blue widget under $50",
        constraints=Constraint(
            max_total_cents=5000,
            allowed_categories=["widgets"],
            max_quantity=1,
            required_attributes={"color": "blue"},
        ),
        human_present=False,
        created_at=T0,
        signer="user",
        signature="",
    )
    intent = intent.model_copy(update={"signature": sign(intent, user_priv)})

    cart = CartMandate(
        mandate_id="cart-1",
        intent_mandate_hash=mandate_hash(intent),
        merchant_id="merchant-1",
        items=[
            CartItem(
                product_id="p-1",
                title="Blue widget",
                category="widgets",
                unit_price_cents=4000,
                quantity=1,
                attributes={"color": "blue"},
            )
        ],
        total_cents=4000,
        created_at=T0,
        signer="agent",
        signature="",
    )
    cart = cart.model_copy(update={"signature": sign(cart, agent_priv)})

    payment = PaymentMandate(
        mandate_id="pay-1",
        cart_mandate_hash=mandate_hash(cart),
        amount_cents=4000,
        payment_method_token="tok_sim_abc",
        agent_involved=True,
        created_at=T0,
        signer="agent",
        signature="",
    )
    payment = payment.model_copy(update={"signature": sign(payment, agent_priv)})

    listing = ListingSnapshot(
        product_id="p-1",
        merchant_id="merchant-1",
        title="Blue widget",
        description="A blue widget",
        unit_price_cents=4000,
        category="widgets",
        attributes={"color": "blue"},
        captured_at=T0,
    )
    case = CaseFile(
        case_id="case-1",
        public_keys={"user": user_pub, "agent": agent_pub},
        intent=intent,
        cart=cart,
        payment=payment,
        trace=[
            TraceStep(
                step_id="s1",
                kind="instruction",
                source="user",
                content="Buy a blue widget under $50",
                timestamp=T0,
            )
        ],
        listings_at_purchase=[listing],
        listing_after=listing,
        delivered=DeliveredItem(product_id="p-1", attributes={"color": "blue"}),
    )
    return case, {"user": user_priv, "agent": agent_priv}


@pytest.fixture
def signed_case():
    return make_case_file()
