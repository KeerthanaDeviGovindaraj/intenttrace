"""Tests for the PayGate benchmark run (case conversion, groups, isolation)."""

from __future__ import annotations

import sqlite3

import pytest

from intenttrace.bench import case_to_request, run_paygate_bench
from intenttrace.sim.generate import build_cases

PAYMENT_ONLY = {"amount_altered", "cart_hash_altered"}


@pytest.fixture(scope="module")
def generated():
    return build_cases(40, 7)


def test_conversion_yields_valid_request_without_payment(generated):
    for g in generated:
        req = case_to_request(g.case)
        dumped = req.model_dump_json()
        assert "payment" not in req.model_dump()
        assert g.case.payment.payment_method_token not in dumped
        step_ids = {s.step_id for s in g.case.trace if s.source in ("merchant", "review", "external_agent")}
        assert {c.item_id for c in req.content} == step_ids
        assert req.cart == g.case.cart


def test_groups_and_excluded_counts(generated, tmp_path, monkeypatch):
    monkeypatch.setenv("INTENTTRACE_DB", str(tmp_path / "user.db"))
    cases = [g.case for g in generated]
    labels = {g.label["case_id"]: g.label for g in generated}
    out = run_paygate_bench(cases, labels, None, seed=7)

    def count(pred):
        return sum(1 for g in generated if pred(g.label))

    merchant = count(lambda lb: lb["label"] == "MERCHANT_MISREPRESENTATION")
    payment = count(lambda lb: lb["label"] == "INTEGRITY_FAILURE" and lb["cause"] in PAYMENT_ONLY)
    legit = count(lambda lb: lb["label"] == "LEGITIMATE")
    assert out["excluded"]["merchant_misrepresentation"]["count"] == merchant
    assert out["excluded"]["payment_only_integrity"]["count"] == payment
    assert out["excluded"]["merchant_misrepresentation"]["reason"]
    assert out["legitimate"]["n"] == legit
    assert out["attack"]["n"] == len(cases) - merchant - payment - legit
    for grp in ("attack", "legitimate"):
        total = sum(out[grp][k] for k in ("block_rate", "ask_human_rate", "allow_rate"))
        assert total == pytest.approx(1.0)
    assert out["false_block_rate"] == out["legitimate"]["block_rate"]
    assert out["latency_ms"]["p50"] <= out["latency_ms"]["p95"]
    assert "MERCHANT_MISREPRESENTATION" not in out["block_rate_by_label"]
    assert not PAYMENT_ONLY & set(out["block_rate_by_cause"])


def test_user_db_untouched(generated, tmp_path, monkeypatch):
    user_db = tmp_path / "user.db"
    monkeypatch.setenv("INTENTTRACE_DB", str(user_db))
    monkeypatch.setenv("PAYGATE_KEY_FILE", str(tmp_path / "user.key"))
    cases = [g.case for g in generated[:5]]
    labels = {g.label["case_id"]: g.label for g in generated[:5]}
    run_paygate_bench(cases, labels, None)
    assert not (tmp_path / "user.key").exists()
    assert not list(tmp_path.glob("user.db*"))
    if user_db.exists():
        with sqlite3.connect(user_db) as conn:
            assert conn.execute("SELECT count(*) FROM decisions").fetchone()[0] == 0


def test_missing_label_raises(generated):
    with pytest.raises(ValueError):
        run_paygate_bench([generated[0].case], {}, None)
