"""Smoke tests for the PayGate hypothesis strategies."""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given, settings
from strategies_paygate import facts, mutated_request, signed_request

from intenttrace.checks.integrity import check_integrity
from intenttrace.paygate import Facts, GateRequest, RequestError, request_to_case, validate_request

_SETTINGS = settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.too_slow])


@_SETTINGS
@given(facts())
def test_facts_strategy_builds_facts(f: Facts) -> None:
    assert isinstance(f, Facts)


@_SETTINGS
@given(signed_request())
def test_signed_request_is_valid_and_signed(req: GateRequest) -> None:
    validated = validate_request(req)
    result = check_integrity(request_to_case(validated))
    assert [f for f in result.failures if not (f.field or "").startswith("payment.")] == []


@_SETTINGS
@given(mutated_request())
def test_mutated_request_is_rejected(raw: dict) -> None:
    with pytest.raises(RequestError):
        validate_request(raw)
