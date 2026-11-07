"""Property test for the PayGate decision log chain (paygate design.md, Property 9)."""

from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
from pathlib import Path

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from intenttrace.paygate_log import ZERO_HASH, DecisionLog, RecordInput, verify_decision_log

_SETTINGS = settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)

_TAMPERS = ["body", "signature", "previous_hash", "record_hash", "delete"]


def _flip(value: str) -> str:
    return ("a" if value[0] != "a" else "b") + value[1:]


@st.composite
def tampered_log(draw):
    """(n, mode, k): a log of n records plus a tamper mode applied to record index k."""
    n = draw(st.integers(min_value=3, max_value=6))
    mode = draw(st.sampled_from(_TAMPERS + ["none"]))
    if mode == "delete":
        k = draw(st.integers(min_value=1, max_value=n - 2))  # a middle record
    else:
        k = draw(st.integers(min_value=0, max_value=n - 1))
    decisions = draw(st.lists(st.sampled_from(["ALLOW", "BLOCK", "ASK_HUMAN"]), min_size=n, max_size=n))
    return n, mode, k, decisions


def _build(tmp: Path, n: int, decisions: list[str]) -> tuple[Path, list[str]]:
    db = tmp / "log.db"
    log = DecisionLog(db)  # key file is created once, next to the db, and reused for every append
    try:
        ids = [
            log.append(
                RecordInput(
                    decision=d,  # type: ignore[arg-type]
                    reason_codes=["CODE"],
                    explanation=f"record {i}",
                    request_hash="f" * 64,
                )
            ).record_id
            for i, d in enumerate(decisions[:n])
        ]
    finally:
        log.close()
    return db, ids


def _tamper(db: Path, ids: list[str], mode: str, k: int) -> None:
    conn = sqlite3.connect(db)
    try:
        rid = ids[k]
        if mode == "delete":
            conn.execute("DELETE FROM decisions WHERE record_id = ?", (rid,))
        elif mode in ("body", "signature"):
            (body,) = conn.execute("SELECT body FROM decisions WHERE record_id = ?", (rid,)).fetchone()
            data = json.loads(body)
            if mode == "body":
                data["explanation"] += " tampered"
            else:
                data["signature"] = _flip(data["signature"])
            conn.execute("UPDATE decisions SET body = ? WHERE record_id = ?", (json.dumps(data), rid))
        else:
            (old,) = conn.execute(f"SELECT {mode} FROM decisions WHERE record_id = ?", (rid,)).fetchone()
            conn.execute(f"UPDATE decisions SET {mode} = ? WHERE record_id = ?", (_flip(old), rid))
        conn.commit()
    finally:
        conn.close()


# Feature: paygate, Property 9: Chain verifies, and any tamper is located
# Validates: Requirements 9.3, 9.4, 9.5, 9.7
@_SETTINGS
@given(tampered_log())
def test_chain_verifies_and_any_tamper_is_located(case):
    n, mode, k, decisions = case
    tmp = Path(tempfile.mkdtemp(prefix="paygate-prop9-"))
    try:
        db, ids = _build(tmp, n, decisions)

        if mode == "none":
            conn = sqlite3.connect(db)
            try:
                rows = conn.execute(
                    "SELECT previous_hash, record_hash FROM decisions ORDER BY seq"
                ).fetchall()
            finally:
                conn.close()
            assert rows[0][0] == ZERO_HASH
            for prev_row, row in zip(rows, rows[1:], strict=False):
                assert row[0] == prev_row[1]
            assert verify_decision_log(db) is None
            return

        _tamper(db, ids, mode, k)
        expected = ids[k + 1] if mode == "delete" else ids[k]
        assert verify_decision_log(db) == expected
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
