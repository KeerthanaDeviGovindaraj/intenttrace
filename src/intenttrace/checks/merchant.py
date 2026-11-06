"""Stage 3: merchant consistency (design.md section 5). Deterministic, never calls an LLM."""

from __future__ import annotations

from pydantic import BaseModel, Field

from intenttrace.models import CaseFile, Finding, ListingSnapshot


class MerchantResult(BaseModel):
    ok: bool
    material: list[Finding] = Field(default_factory=list)
    non_material: list[Finding] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)


def _finding(kind: str, detail: str, field: str, expected, actual) -> Finding:
    return Finding(
        kind=kind,
        detail=detail,
        field=field,
        expected=expected,
        actual=actual,
        method="deterministic",
    )


def _snapshot_for(case: CaseFile, product_id: str) -> ListingSnapshot | None:
    return next((s for s in case.listings_at_purchase if s.product_id == product_id), None)


def _diff_attributes(
    prefix: str,
    before: dict[str, str],
    after: dict[str, str],
    required: set[str],
    material: list[Finding],
    non_material: list[Finding],
) -> None:
    """Diff attribute dicts. Declared (in `before`) or required keys are material."""
    for key in sorted(set(before) | set(after)):
        expected, actual = before.get(key), after.get(key)
        if expected == actual:
            continue
        if key in before or key in required:
            kind = "merchant_difference"
            detail = f"Attribute '{key}' differs from the listing at purchase time."
            sink = material
        else:
            kind = "merchant_nonmaterial_difference"
            detail = f"Undeclared attribute '{key}' differs from the listing at purchase time."
            sink = non_material
        sink.append(_finding(kind, detail, f"{prefix}.{key}", expected, actual))


def check_merchant(case: CaseFile) -> MerchantResult:
    """Compare the purchase-time listing with the later listing and the delivered item."""
    material: list[Finding] = []
    non_material: list[Finding] = []
    skipped: list[str] = []
    required = set(case.intent.constraints.required_attributes)

    after = case.listing_after
    if after is None:
        skipped.append("listing_after: not present")
    else:
        before = _snapshot_for(case, after.product_id)
        if before is None:
            skipped.append(f"listing_after: no purchase-time snapshot for '{after.product_id}'")
        else:
            if before.unit_price_cents != after.unit_price_cents:
                material.append(
                    _finding(
                        "merchant_difference",
                        "Price changed after purchase.",
                        "listing_after.unit_price_cents",
                        before.unit_price_cents,
                        after.unit_price_cents,
                    )
                )
            for name in ("title", "description"):
                if getattr(before, name) != getattr(after, name):
                    non_material.append(
                        _finding(
                            "merchant_nonmaterial_difference",
                            f"Listing {name} wording changed after purchase.",
                            f"listing_after.{name}",
                            getattr(before, name),
                            getattr(after, name),
                        )
                    )
            _diff_attributes(
                "listing_after.attributes",
                before.attributes,
                after.attributes,
                required,
                material,
                non_material,
            )

    delivered = case.delivered
    if delivered is None:
        skipped.append("delivered: not present")
    else:
        before = _snapshot_for(case, delivered.product_id)
        if before is None:
            skipped.append(f"delivered: no purchase-time snapshot for '{delivered.product_id}'")
        else:
            _diff_attributes(
                "delivered.attributes",
                before.attributes,
                delivered.attributes,
                required,
                material,
                non_material,
            )

    return MerchantResult(ok=not material, material=material, non_material=non_material, skipped=skipped)
