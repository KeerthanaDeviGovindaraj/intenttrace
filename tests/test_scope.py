"""Tests for checks/scope.py: a passing and failing case per constraint."""

from __future__ import annotations

from intenttrace.checks.scope import check_scope


def _with(case, constraint_updates=None, cart_updates=None, item_updates=None):
    intent = case.intent
    if constraint_updates:
        intent = intent.model_copy(
            update={"constraints": intent.constraints.model_copy(update=constraint_updates)}
        )
    cart = case.cart
    if item_updates:
        cart = cart.model_copy(update={"items": [cart.items[0].model_copy(update=item_updates)]})
    if cart_updates:
        cart = cart.model_copy(update=cart_updates)
    return case.model_copy(update={"intent": intent, "cart": cart})


def _fields(result):
    return [v.field for v in result.violations]


def test_valid_case_in_scope(signed_case):
    case, _ = signed_case
    result = check_scope(case)
    assert result.ok and result.violations == []


def test_max_total(signed_case):
    case, _ = signed_case
    assert check_scope(_with(case, {"max_total_cents": 4000})).ok
    result = check_scope(_with(case, {"max_total_cents": 3999}))
    v = result.violations[0]
    assert _fields(result) == ["cart.total_cents"]
    assert (v.kind, v.method, v.actual) == ("scope_violation", "deterministic", 4000)


def test_max_unit_price(signed_case):
    case, _ = signed_case
    assert check_scope(_with(case, {"max_unit_price_cents": 4000})).ok
    result = check_scope(_with(case, {"max_unit_price_cents": 3999}))
    assert _fields(result) == ["cart.items[0].unit_price_cents"]


def test_allowed_categories(signed_case):
    case, _ = signed_case
    assert check_scope(_with(case, {"allowed_categories": ["widgets", "gadgets"]})).ok
    result = check_scope(_with(case, {"allowed_categories": ["gadgets"]}))
    assert _fields(result) == ["cart.items[0].category"]
    assert result.violations[0].actual == "widgets"


def test_allowed_merchants(signed_case):
    case, _ = signed_case
    assert check_scope(_with(case, {"allowed_merchants": ["merchant-1"]})).ok
    result = check_scope(_with(case, {"allowed_merchants": ["merchant-2"]}))
    assert _fields(result) == ["cart.merchant_id"]
    assert result.violations[0].actual == "merchant-1"


def test_max_quantity(signed_case):
    case, _ = signed_case
    assert check_scope(_with(case, item_updates={"quantity": 1})).ok
    result = check_scope(_with(case, item_updates={"quantity": 2}))
    assert _fields(result) == ["cart.items[0].quantity"]
    assert result.violations[0].actual == 2


def test_required_attributes_case_insensitive_pass(signed_case):
    case, _ = signed_case
    result = check_scope(_with(case, item_updates={"attributes": {"Color": "BLUE"}}))
    assert result.ok


def test_required_attributes_wrong_value(signed_case):
    case, _ = signed_case
    result = check_scope(_with(case, item_updates={"attributes": {"color": "red"}}))
    assert _fields(result) == ["cart.items[0].attributes.color"]
    v = result.violations[0]
    assert (v.expected, v.actual) == ("blue", "red")


def test_required_attributes_missing(signed_case):
    case, _ = signed_case
    result = check_scope(_with(case, item_updates={"attributes": {}}))
    assert _fields(result) == ["cart.items[0].attributes.color"]
    assert result.violations[0].actual is None


def test_required_attributes_not_substring_match(signed_case):
    case, _ = signed_case
    result = check_scope(_with(case, item_updates={"attributes": {"color": "light blue"}}))
    assert not result.ok


def test_expiry_not_expired(signed_case):
    case, _ = signed_case
    assert check_scope(_with(case, {"expires_at": "2025-01-02T00:00:00Z"})).ok


def test_expiry_equal_is_not_expired(signed_case):
    case, _ = signed_case
    assert check_scope(_with(case, {"expires_at": "2025-01-01T00:00:00Z"})).ok


def test_expired(signed_case):
    case, _ = signed_case
    result = check_scope(_with(case, {"expires_at": "2024-12-31T23:59:59Z"}))
    assert _fields(result) == ["cart.created_at"]
    assert result.violations[0].actual == "2025-01-01T00:00:00Z"


def test_expiry_compares_instants_across_offsets(signed_case):
    case, _ = signed_case
    # 2025-01-01T00:00:00Z equals 2025-01-01T01:00:00+01:00, so this is not expired.
    assert check_scope(_with(case, {"expires_at": "2025-01-01T01:00:00+01:00"})).ok


def test_reports_every_violation(signed_case):
    case, _ = signed_case
    result = check_scope(
        _with(
            case,
            {"max_total_cents": 1, "allowed_merchants": ["x"], "expires_at": "2000-01-01T00:00:00Z"},
        )
    )
    assert set(_fields(result)) == {"cart.total_cents", "cart.merchant_id", "cart.created_at"}
    assert not result.ok
