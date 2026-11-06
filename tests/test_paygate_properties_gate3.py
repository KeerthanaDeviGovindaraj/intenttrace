"""Property tests for gate_purchase (paygate design.md, Properties 7, 8 and 10).

Every call uses a temporary DecisionLog with a temporary key, so the user's database is never
touched. Failures are injected with a context manager per example (not the monkeypatch fixture).
"""

from __future__ import annotations

import hashlib
import sqlite3
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest import mock

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from strategies_paygate import TRIGGER_PHRASES, mutated_request, signed_request

from intenttrace import crypto
from intenttrace import paygate as paygate_mod
from intenttrace.paygate import ContentItem, GateRequest, GateResult, gate_purchase
from intenttrace.paygate_log import (
    DecisionLog,
    _create_key,
    _public_b64,
    _read_key,
    decision_markdown,
)

_SETTINGS = settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)


@contextmanager
def _temp_log() -> Iterator[tuple[DecisionLog, Path, Path]]:
    """A DecisionLog in a temp dir with an explicit, freshly created key. Yields (log, db, key)."""
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "log.db"
        key = Path(tmp) / "gate.key"
        _create_key(key)
        log = DecisionLog(db, key_file=key)
        try:
            yield log, db, key
        finally:
            log.close()


def _row_count(db: Path) -> int:
    conn = sqlite3.connect(db)
    try:
        return conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]
    finally:
        conn.close()


_CHECK_NAMES = {
    "check_integrity": "integrity",
    "check_scope": "scope",
    "detect": "detect",
    "check_deviation": "deviation",
    "run_replay": "replay",
}


def _checks_that_run(req: GateRequest, baseline: GateResult, replay: bool) -> list[str]:
    """Names (as imported in intenttrace.paygate) of checks that actually run for this request."""
    codes = baseline.reason_codes
    names = ["check_integrity"]
    if any(c.startswith("INTEGRITY_") for c in codes):
        return names
    names.append("check_scope")
    if "SCOPE_VIOLATION" in codes:
        return names
    names.append("detect")
    if replay and req.agent_config is not None and baseline.spans:
        names.append("run_replay")
    if req.listings:
        names.append("check_deviation")
    return names


# Feature: paygate, Property 7: Fail-safe on check failure or missing keys
@_SETTINGS
@given(signed_request(), st.data())
def test_property_7_fail_safe_on_check_failure(req: GateRequest, data: st.DataObject) -> None:
    """**Validates: Requirements 5.1, 5.2, 5.5**"""
    with _temp_log() as (log, _db, _key):
        baseline = gate_purchase(req, log=log)
        running = _checks_that_run(req, baseline, replay=True)
        target = data.draw(st.sampled_from(running))
        with mock.patch.object(paygate_mod, target, side_effect=RuntimeError("injected")):
            result = gate_purchase(req, log=log)
    assert result.decision != "ALLOW"
    assert "CHECK_FAILED" in result.reason_codes
    assert _CHECK_NAMES[target] in result.explanation


# Feature: paygate, Property 7: Fail-safe on check failure or missing keys
@_SETTINGS
@given(signed_request(), st.data())
def test_property_7_missing_public_key_blocks(req: GateRequest, data: st.DataObject) -> None:
    """**Validates: Requirements 5.1, 5.2, 5.5**

    The user key always verifies the intent; the agent key is needed only when the agent signed the cart.
    """
    removable = ["user"] + (["agent"] if req.cart.signer == "agent" else [])
    missing = data.draw(st.sampled_from(removable))
    keys = {k: v for k, v in req.public_keys.items() if k != missing}
    broken = req.model_copy(update={"public_keys": keys})
    with _temp_log() as (log, _db, _key):
        result = gate_purchase(broken, log=log)
    assert result.decision == "BLOCK"
    assert "INTEGRITY_SIGNATURE_INVALID" in result.reason_codes


_junk = st.one_of(
    st.none(),
    st.integers(),
    st.text(max_size=20),
    st.lists(st.integers(), max_size=3),
    st.dictionaries(st.text(max_size=5), st.integers(), max_size=3),
)
_any_input = st.one_of(signed_request(), mutated_request(), _junk)


# Feature: paygate, Property 8: One record per call, and records round trip
@_SETTINGS
@given(st.lists(_any_input, min_size=1, max_size=4))
def test_property_8_one_record_per_call_and_round_trip(inputs: list[Any]) -> None:
    """**Validates: Requirements 6.4, 9.1, 9.2**"""
    with _temp_log() as (log, db, key):
        public = _public_b64(_read_key(key))
        previous_hash = "0" * 64
        for i, item in enumerate(inputs):
            before = _row_count(db)
            result = gate_purchase(item, log=log)
            assert _row_count(db) == before + 1
            assert i + 1 == _row_count(db)
            assert result.record_id is not None

            record = log.get(result.record_id)
            assert record is not None
            assert record.decision == result.decision
            assert record.reason_codes == list(result.reason_codes)
            assert record.explanation == result.explanation
            assert record.spans == result.spans
            assert record.skipped_checks == result.skipped_checks
            assert record.previous_hash == previous_hash
            assert crypto.verify(record, public)
            if isinstance(item, GateRequest):
                expected = hashlib.sha256(crypto.canonical(item.model_dump())).hexdigest()
                assert record.request_hash == expected
            previous_hash = crypto.mandate_hash(record)


@st.composite
def _request_with_marker(draw: st.DrawFn) -> tuple[GateRequest, str]:
    req = draw(signed_request())
    letters = st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=12, max_size=16)
    marker = "qzx" + draw(letters)
    phrase = draw(st.sampled_from(TRIGGER_PHRASES))
    content = [c.model_copy(update={"text": f"{c.text} {marker}"}) for c in req.content]
    content.append(
        ContentItem(item_id="marker-item", source="review", text=f"{phrase} {marker}", product_id=None)
    )
    return req.model_copy(update={"content": content}), marker


# Feature: paygate, Property 10: Untrusted text never leaks into stored or returned text
@_SETTINGS
@given(_request_with_marker())
def test_property_10_untrusted_text_never_leaks(case: tuple[GateRequest, str]) -> None:
    """**Validates: Requirements 2.5, 9.11**"""
    req, marker = case
    with _temp_log() as (log, db, _key):
        result = gate_purchase(req, log=log)
        assert result.record_id is not None
        record = log.get(result.record_id)
        assert record is not None
        conn = sqlite3.connect(db)
        try:
            stored = [tuple(r) for r in conn.execute("SELECT * FROM decisions").fetchall()]
        finally:
            conn.close()
        evidence = decision_markdown(record)

    assert marker not in repr(stored)
    assert marker not in result.explanation
    assert marker not in result.model_dump_json()
    assert marker not in evidence
