"""Tests for checks/merchant.py: material versus non-material differences."""

from __future__ import annotations

from intenttrace.checks.merchant import check_merchant
from intenttrace.models import DeliveredItem


def _with(case, after_updates=None, delivered_attrs=None, purchase_attrs=None, required=None):
    updates = {}
    if after_updates is not None:
        updates["listing_after"] = case.listing_after.model_copy(update=after_updates)
    if delivered_attrs is not None:
        updates["delivered"] = DeliveredItem(product_id="p-1", attributes=delivered_attrs)
    if purchase_attrs is not None:
        snap = case.listings_at_purchase[0].model_copy(update={"attributes": purchase_attrs})
        updates["listings_at_purchase"] = [snap]
    if required is not None:
        c = case.intent.constraints.model_copy(update={"required_attributes": required})
        updates["intent"] = case.intent.model_copy(update={"constraints": c})
    return case.model_copy(update=updates)


def test_consistent_case_ok(signed_case):
    case, _ = signed_case
    result = check_merchant(case)
    assert result.ok
    assert result.material == [] and result.non_material == [] and result.skipped == []


def test_price_change_is_material(signed_case):
    case, _ = signed_case
    result = check_merchant(_with(case, {"unit_price_cents": 4500}))
    assert not result.ok
    f = result.material[0]
    assert (f.field, f.expected, f.actual) == ("listing_after.unit_price_cents", 4000, 4500)
    assert f.kind == "merchant_difference" and f.method == "deterministic"


def test_required_attribute_change_is_material(signed_case):
    case, _ = signed_case
    result = check_merchant(_with(case, {"attributes": {"color": "red"}}))
    assert not result.ok
    f = result.material[0]
    assert (f.field, f.expected, f.actual) == ("listing_after.attributes.color", "blue", "red")


def test_required_attribute_not_declared_on_listing_is_material(signed_case):
    case, _ = signed_case
    case = _with(case, purchase_attrs={}, required={"color": "blue"})
    result = check_merchant(_with(case, {"attributes": {"color": "red"}}))
    assert not result.ok
    assert result.material[0].expected is None


def test_declared_attribute_change_is_material(signed_case):
    case, _ = signed_case
    case = _with(case, purchase_attrs={"color": "blue", "size": "M"}, required={})
    result = check_merchant(_with(case, {"attributes": {"color": "blue", "size": "L"}}))
    assert not result.ok
    f = result.material[0]
    assert (f.field, f.expected, f.actual) == ("listing_after.attributes.size", "M", "L")


def test_undeclared_attribute_is_non_material(signed_case):
    case, _ = signed_case
    result = check_merchant(_with(case, {"attributes": {"color": "blue", "origin": "EU"}}))
    assert result.ok
    assert result.non_material[0].field == "listing_after.attributes.origin"


def test_delivered_mismatch_is_material(signed_case):
    case, _ = signed_case
    result = check_merchant(_with(case, delivered_attrs={"color": "green"}))
    assert not result.ok
    f = result.material[0]
    assert (f.field, f.expected, f.actual) == ("delivered.attributes.color", "blue", "green")


def test_delivered_missing_declared_attribute_is_material(signed_case):
    case, _ = signed_case
    result = check_merchant(_with(case, delivered_attrs={}))
    assert not result.ok
    assert result.material[0].actual is None


def test_title_and_description_only_are_non_material(signed_case):
    case, _ = signed_case
    result = check_merchant(_with(case, {"title": "Azure widget", "description": "New copy"}))
    assert result.ok and result.material == []
    assert {f.field for f in result.non_material} == {
        "listing_after.title",
        "listing_after.description",
    }
    assert all(f.kind == "merchant_nonmaterial_difference" for f in result.non_material)


def test_absent_data_is_skipped(signed_case):
    case, _ = signed_case
    result = check_merchant(case.model_copy(update={"listing_after": None, "delivered": None}))
    assert result.ok
    assert result.material == [] and result.non_material == []
    assert len(result.skipped) == 2


def test_only_delivered_absent_still_checks_listing_after(signed_case):
    case, _ = signed_case
    case = _with(case, {"unit_price_cents": 1})
    result = check_merchant(case.model_copy(update={"delivered": None}))
    assert not result.ok
    assert result.skipped == ["delivered: not present"]
