"""Unit tests for PayGate models and request validation."""

from __future__ import annotations

import pytest
from conftest import make_case_file
from pydantic import ValidationError

from intenttrace.paygate import (
    ErrorItem,
    GateRequest,
    GateResult,
    RequestError,
    validate_request,
)

CARD = "4111111111111111"  # Luhn-valid test number


def _request(**over) -> dict:
    case, _ = make_case_file()
    base = {
        "public_keys": case.public_keys,
        "intent": case.intent.model_dump(),
        "cart": case.cart.model_dump(),
        "content": [{"source": "merchant", "text": "Nice widget"}],
    }
    base.update(over)
    return base


def _errors(raw) -> list[ErrorItem]:
    with pytest.raises(RequestError) as ei:
        validate_request(raw)
    return ei.value.errors


def test_valid_request_defaults_item_ids():
    req = validate_request(
        _request(content=[{"source": "review", "text": "a"}, {"source": "qa", "text": "b"}])
    )
    assert [c.item_id for c in req.content] == ["c0", "c1"]
    assert validate_request(req).cart.mandate_id == req.cart.mandate_id


def test_content_is_optional():
    raw = _request()
    raw.pop("content")
    assert validate_request(raw).content == []


def test_duplicate_item_ids_rejected():
    raw = _request(
        content=[
            {"item_id": "x", "source": "review", "text": "a"},
            {"item_id": "x", "source": "qa", "text": "b"},
        ]
    )
    assert [e.path for e in _errors(raw)] == ["$.content"]


def test_default_id_colliding_with_explicit_id_rejected():
    raw = _request(
        content=[
            {"item_id": "c1", "source": "review", "text": "a"},
            {"source": "qa", "text": "b"},
        ]
    )
    assert _errors(raw)[0].path == "$.content"


def test_empty_cart_rejected():
    raw = _request()
    raw["cart"]["items"] = []
    assert _errors(raw)[0].path == "$.cart"


def test_unknown_field_path():
    errs = _errors(_request(surprise=1))
    assert [(e.path, e.msg) for e in errs] == [("$.surprise", "unknown field")]


def test_missing_field_and_nested_path():
    raw = _request()
    del raw["cart"]["items"][0]["quantity"]
    assert _errors(raw)[0].path == "$.cart.items[0].quantity"


def test_luhn_number_rejected_without_echo():
    raw = _request(content=[{"source": "review", "text": f"pay with {CARD} now"}])
    errs = _errors(raw)
    assert errs and errs[0].path == "$.content[0]"
    assert CARD not in repr(errs)


def test_non_luhn_digits_allowed():
    raw = _request(content=[{"source": "review", "text": "order 1234567890123456"}])
    assert validate_request(raw).content[0].text.startswith("order")


def test_oversize_rejected():
    raw = _request(content=[{"source": "review", "text": "x" * 1_100_000}])
    with pytest.raises(RequestError) as ei:
        validate_request(raw)
    assert ei.value.oversize


@pytest.mark.parametrize("raw", [None, 5, [1], "not json", b"\xff\xfe"])
def test_non_object_inputs_rejected(raw):
    errs = _errors(raw)
    assert errs[0].path == "$"


def test_errors_never_echo_wrong_type_values():
    raw = _request()
    raw["cart"]["total_cents"] = "SECRET-VALUE"
    assert "SECRET-VALUE" not in repr(_errors(raw))


def test_gate_result_constraints():
    with pytest.raises(ValidationError):
        GateResult(decision="ALLOW", reason_codes=[], explanation="x")
    with pytest.raises(ValidationError):
        GateResult(decision="ALLOW", reason_codes=["CLEAN"], explanation="x" * 401)
    assert GateResult(decision="ALLOW", reason_codes=["CLEAN"], explanation="ok").record_id is None


def test_gate_request_forbids_extra():
    with pytest.raises(ValidationError):
        GateRequest.model_validate({**_request(), "x": 1})
