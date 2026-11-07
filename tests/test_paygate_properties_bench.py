"""Property test for PayGate benchmark conversion and rates (paygate design.md, Property 11)."""

from __future__ import annotations

import functools

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from intenttrace.bench import (
    DECIDABLE,
    EXCLUDED_REASONS,
    PAYGATE_DECISIONS,
    _block_rate_by,
    _decision_rates,
    _paygate_group,
    _percentile,
    case_to_request,
)
from intenttrace.paygate import GateRequest
from intenttrace.sim.generate import build_cases

_ROW_SETTINGS = settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
# build_cases is expensive, so this property runs fewer examples; results are cached per (n, seed).
_CASE_SETTINGS = settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.too_slow])

_CAUSES = [None, "amount_altered", "cart_hash_altered", "intent_signature", "cart_signature", "other"]


@functools.cache
def _cached_cases(n: int, seed: int):
    return build_cases(n, seed)


@st.composite
def labeled_rows(draw):
    """Rows shaped like those built in run_paygate_bench, without running the gate."""
    rows = []
    for _ in range(draw(st.integers(0, 40))):
        label = {
            "label": draw(st.sampled_from(DECIDABLE)),
            "cause": draw(st.sampled_from(_CAUSES)),
            "attack_type": draw(st.sampled_from([None, "injection", "swap", "drift"])),
        }
        rows.append(
            {
                "group": _paygate_group(label),
                **label,
                "decision": draw(st.sampled_from(PAYGATE_DECISIONS)),
            }
        )
    return rows


# Feature: paygate, Property 11: Benchmark conversion and rates
# **Validates: Requirements 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7**
@_CASE_SETTINGS
@given(n=st.integers(6, 12), seed=st.integers(0, 5))
def test_case_to_request_is_valid_and_has_no_payment(n, seed):
    for generated in _cached_cases(n, seed):
        request = case_to_request(generated.case)
        assert isinstance(request, GateRequest)
        GateRequest.model_validate(request.model_dump())
        assert request.cart.items
        assert "payment" not in GateRequest.model_fields
        assert "payment" not in request.model_dump()
        assert "payment" not in " ".join(request.model_dump())


# Feature: paygate, Property 11: Benchmark conversion and rates
# **Validates: Requirements 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7**
@_ROW_SETTINGS
@given(rows=labeled_rows())
def test_group_rates_sum_to_one_and_exclusions_are_separate(rows):
    attack = [r for r in rows if r["group"] == "attack"]
    legit = [r for r in rows if r["group"] == "legitimate"]
    for group in (attack, legit):
        rates = _decision_rates(group)
        assert rates["n"] == len(group)
        values = [rates[f"{d.lower()}_rate"] for d in PAYGATE_DECISIONS]
        assert all(0.0 <= v <= 1.0 for v in values)
        assert sum(values) == pytest.approx(1.0) if group else sum(values) == 0.0

    for r in attack + legit:
        assert r["label"] != "MERCHANT_MISREPRESENTATION"
        assert not (
            r["label"] == "INTEGRITY_FAILURE" and r["cause"] in ("amount_altered", "cart_hash_altered")
        )
    excluded = {name: sum(1 for r in rows if r["group"] == name) for name in EXCLUDED_REASONS}
    assert excluded["merchant_misrepresentation"] == sum(
        1 for r in rows if r["label"] == "MERCHANT_MISREPRESENTATION"
    )
    assert excluded["payment_only_integrity"] == sum(
        1
        for r in rows
        if r["label"] == "INTEGRITY_FAILURE" and r["cause"] in ("amount_altered", "cart_hash_altered")
    )
    assert len(attack) + len(legit) + sum(excluded.values()) == len(rows)

    for key in ("label", "attack_type", "cause"):
        for entry in _block_rate_by(attack + legit, key).values():
            assert entry["n"] > 0
            assert 0.0 <= entry["block_rate"] <= 1.0


# Feature: paygate, Property 11: Benchmark conversion and rates
# **Validates: Requirements 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7**
@_ROW_SETTINGS
@given(values=st.lists(st.floats(0, 1e6, allow_nan=False), max_size=60))
def test_p50_not_above_p95(values):
    assert _percentile(values, 50) <= _percentile(values, 95)
