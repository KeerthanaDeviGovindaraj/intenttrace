"""Stage 2: scope checks (design.md section 4). Deterministic, never calls an LLM."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field

from intenttrace.models import CaseFile, Finding


class ScopeResult(BaseModel):
    ok: bool
    violations: list[Finding] = Field(default_factory=list)


def _violation(detail: str, field: str, expected, actual) -> Finding:
    return Finding(
        kind="scope_violation",
        detail=detail,
        field=field,
        expected=expected,
        actual=actual,
        method="deterministic",
    )


def _parse_ts(value: str) -> datetime | None:
    """Parse an ISO 8601 timestamp; naive values are treated as UTC. None if unparseable."""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def check_scope(case: CaseFile) -> ScopeResult:
    """Check the cart against every Intent constraint and collect every violation."""
    violations: list[Finding] = []
    constraints, cart = case.intent.constraints, case.cart

    if constraints.max_total_cents is not None and cart.total_cents > constraints.max_total_cents:
        violations.append(
            _violation(
                "Cart total exceeds the maximum total price.",
                "cart.total_cents",
                f"<= {constraints.max_total_cents}",
                cart.total_cents,
            )
        )

    if constraints.allowed_merchants is not None and cart.merchant_id not in constraints.allowed_merchants:
        violations.append(
            _violation(
                "Cart merchant is not in the allowed merchants.",
                "cart.merchant_id",
                list(constraints.allowed_merchants),
                cart.merchant_id,
            )
        )

    for i, item in enumerate(cart.items):
        prefix = f"cart.items[{i}]"

        if (
            constraints.max_unit_price_cents is not None
            and item.unit_price_cents > constraints.max_unit_price_cents
        ):
            violations.append(
                _violation(
                    f"Unit price of '{item.product_id}' exceeds the maximum unit price.",
                    f"{prefix}.unit_price_cents",
                    f"<= {constraints.max_unit_price_cents}",
                    item.unit_price_cents,
                )
            )

        if constraints.allowed_categories is not None and item.category not in constraints.allowed_categories:
            violations.append(
                _violation(
                    f"Category of '{item.product_id}' is not an allowed category.",
                    f"{prefix}.category",
                    list(constraints.allowed_categories),
                    item.category,
                )
            )

        if constraints.max_quantity is not None and item.quantity > constraints.max_quantity:
            violations.append(
                _violation(
                    f"Quantity of '{item.product_id}' exceeds the maximum quantity.",
                    f"{prefix}.quantity",
                    f"<= {constraints.max_quantity}",
                    item.quantity,
                )
            )

        item_attrs = {k.lower(): v.lower() for k, v in item.attributes.items()}
        for key, expected in constraints.required_attributes.items():
            actual = item_attrs.get(key.lower())
            if actual != expected.lower():
                violations.append(
                    _violation(
                        f"Required attribute '{key}' of '{item.product_id}' does not match.",
                        f"{prefix}.attributes.{key}",
                        expected,
                        next((v for k, v in item.attributes.items() if k.lower() == key.lower()), None),
                    )
                )

    if constraints.expires_at is not None:
        expiry = _parse_ts(constraints.expires_at)
        created = _parse_ts(cart.created_at)
        if expiry is None or created is None:
            violations.append(
                _violation(
                    "Cart or expiry timestamp could not be parsed.",
                    "cart.created_at",
                    f"parseable timestamp, expiry {constraints.expires_at}",
                    cart.created_at,
                )
            )
        elif created > expiry:
            violations.append(
                _violation(
                    "Cart was created after the intent mandate expired.",
                    "cart.created_at",
                    f"<= {constraints.expires_at}",
                    cart.created_at,
                )
            )

    return ScopeResult(ok=not violations, violations=violations)
