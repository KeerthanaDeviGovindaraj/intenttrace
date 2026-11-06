"""Case file data models (design.md section 1).

Money is integer cents. Times are ISO 8601 UTC strings. Case files hold synthetic data only:
any string containing a Luhn-valid 13-19 digit run is rejected.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

_DIGIT_RUN = re.compile(r"\d+")
_GROUPED_RUN = re.compile(r"(?<!\d)\d{4}(?:[ -]\d{4}){2,3}(?:[ -]\d{1,3})?(?!\d)")


def luhn_valid(digits: str) -> bool:
    """Return True if the digit string passes the Luhn checksum."""
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def contains_card_number(text: str) -> bool:
    """True if text has a 13-19 digit run (optionally space/dash grouped) that passes Luhn."""
    for m in _DIGIT_RUN.finditer(text):
        run = m.group()
        if 13 <= len(run) <= 19 and luhn_valid(run):
            return True
    for m in _GROUPED_RUN.finditer(text):
        run = re.sub(r"[ -]", "", m.group())
        if 13 <= len(run) <= 19 and luhn_valid(run):
            return True
    return False


# Machine-generated fields (hex hashes, base64 signatures/keys) can contain Luhn-valid digit
# runs by chance, so the guard skips them and scans free-text and identifier fields only.
_GUARD_SKIP_KEYS = frozenset({"signature", "intent_mandate_hash", "cart_mandate_hash", "public_keys"})


def _iter_strings(obj: Any):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if k in _GUARD_SKIP_KEYS:
                continue
            yield from _iter_strings(k)
            yield from _iter_strings(v)
    elif isinstance(obj, list | tuple):
        for v in obj:
            yield from _iter_strings(v)


class _Model(BaseModel):
    """Base: forbids extra fields and rejects real-looking card numbers in any string field."""

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _reject_card_numbers(self) -> _Model:
        for s in _iter_strings(self.model_dump()):
            if contains_card_number(s):
                raise ValueError(
                    "value looks like a payment card number (Luhn-valid 13-19 digits); synthetic data only"
                )
        return self


class Constraint(_Model):
    max_total_cents: int | None = None
    max_unit_price_cents: int | None = None
    allowed_categories: list[str] | None = None
    allowed_merchants: list[str] | None = None
    max_quantity: int | None = None
    required_attributes: dict[str, str] = Field(default_factory=dict)
    expires_at: str | None = None


class IntentMandate(_Model):
    mandate_id: str
    user_id: str
    natural_language: str
    constraints: Constraint
    human_present: bool
    created_at: str
    signer: Literal["user"]
    signature: str


class CartItem(_Model):
    product_id: str
    title: str
    category: str
    unit_price_cents: int
    quantity: int
    attributes: dict[str, str]


class CartMandate(_Model):
    mandate_id: str
    intent_mandate_hash: str
    merchant_id: str
    items: list[CartItem]
    total_cents: int
    created_at: str
    signer: Literal["user", "agent"]
    signature: str


class PaymentMandate(_Model):
    mandate_id: str
    cart_mandate_hash: str
    amount_cents: int
    payment_method_token: str
    agent_involved: bool
    created_at: str
    signer: Literal["user", "agent"]
    signature: str


class TraceStep(_Model):
    step_id: str
    kind: Literal["instruction", "observe", "think", "tool_call", "decide"]
    source: Literal["user", "merchant", "review", "external_agent", "agent"]
    content: str
    product_id: str | None = None
    timestamp: str


class ListingSnapshot(_Model):
    product_id: str
    merchant_id: str
    title: str
    description: str
    unit_price_cents: int
    category: str
    attributes: dict[str, str]
    captured_at: str


class DeliveredItem(_Model):
    product_id: str
    attributes: dict[str, str]


class AgentConfig(_Model):
    agent_type: Literal["scripted", "llm"]
    seed: int
    susceptibility: dict[str, float] = Field(default_factory=dict)
    model: str | None = None
    system_prompt: str | None = None


class CaseFile(_Model):
    case_id: str
    public_keys: dict[str, str]
    intent: IntentMandate
    cart: CartMandate
    payment: PaymentMandate
    trace: list[TraceStep]
    listings_at_purchase: list[ListingSnapshot]
    listing_after: ListingSnapshot | None = None
    delivered: DeliveredItem | None = None
    agent_config: AgentConfig | None = None


class Span(_Model):
    """A character range within a trace step's content."""

    step_id: str
    start: int
    end: int
    rule_id: str | None = None
    reason: str | None = None


class Finding(_Model):
    """A forensic finding shared by all pipeline stages."""

    kind: str
    detail: str = ""
    field: str | None = None
    expected: Any = None
    actual: Any = None
    step_ids: list[str] = Field(default_factory=list)
    spans: list[Span] = Field(default_factory=list)
    method: Literal["rule", "llm", "deterministic"] | None = None
