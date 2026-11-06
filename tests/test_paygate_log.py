"""Tests for the signed, hash-chained PayGate decision log."""

from __future__ import annotations

import sqlite3
import stat
import threading

import pytest

from intenttrace.paygate import HighlightedSpan
from intenttrace.paygate_log import (
    ZERO_HASH,
    DecisionLog,
    LogWriteError,
    RecordInput,
    chain_status,
    verify_decision_log,
)


@pytest.fixture(autouse=True)
def _no_key_env(monkeypatch):
    monkeypatch.delenv("PAYGATE_KEY_FILE", raising=False)


def _rec(n: int = 0, decision: str = "ALLOW") -> RecordInput:
    return RecordInput(
        decision=decision,  # type: ignore[arg-type]
        reason_codes=["CLEAN"],
        explanation=f"ok {n}",
        spans=[HighlightedSpan(item_id="c0", start=1, end=5, rule_id="r")],
        request_hash=f"{n:064x}",
    )


def _fill(db, n: int = 3) -> list[str]:
    log = DecisionLog(db)
    ids = [log.append(_rec(i)).record_id for i in range(n)]
    log.close()
    return ids


def test_chain_links_and_verifies(tmp_path):
    db = tmp_path / "t.db"
    log = DecisionLog(db)
    recs = [log.append(_rec(i)) for i in range(3)]
    assert recs[0].previous_hash == ZERO_HASH
    assert recs[1].previous_hash != ZERO_HASH
    assert verify_decision_log(db) is None
    assert chain_status(db) == {"valid": True, "first_invalid_id": None, "count": 3}
    assert log.get(recs[1].record_id) == recs[1]
    assert [r.record_id for r in log.list()] == [r.record_id for r in reversed(recs)]
    assert log.list(decision="BLOCK") == []
    log.close()


def test_genesis_hash_is_64_zeros(tmp_path):
    log = DecisionLog(tmp_path / "g.db")
    assert log.append(_rec()).previous_hash == "0" * 64
    log.close()


def test_empty_log_is_valid(tmp_path):
    assert verify_decision_log(tmp_path / "missing.db") is None
    DecisionLog(tmp_path / "e.db").close()
    assert chain_status(tmp_path / "e.db")["count"] == 0


def test_default_key_file_mode_and_public_key_recorded(tmp_path):
    db = tmp_path / "t.db"
    _fill(db, 1)
    key = tmp_path / "t.db.paygate.key"
    assert stat.S_IMODE(key.stat().st_mode) == 0o600
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT count(*) FROM decision_keys").fetchone()[0] == 1
    conn.close()
    # reuse on reopen: still verifies with the same key
    _fill(db, 1)
    assert verify_decision_log(db) is None


def test_explicit_key_file_never_auto_created(tmp_path, monkeypatch):
    missing = tmp_path / "nokey"
    monkeypatch.setenv("PAYGATE_KEY_FILE", str(missing))
    log = DecisionLog(tmp_path / "t.db")
    with pytest.raises(LogWriteError):
        log.append(_rec())
    assert not missing.exists()
    log.close()


def test_explicit_key_file_loaded(tmp_path, monkeypatch):
    seed_log = DecisionLog(tmp_path / "a.db")
    seed_log.append(_rec())
    seed_log.close()
    key = tmp_path / "a.db.paygate.key"
    monkeypatch.setenv("PAYGATE_KEY_FILE", str(key))
    ids = _fill(tmp_path / "b.db", 2)
    assert verify_decision_log(tmp_path / "b.db") is None
    assert len(ids) == 2
    assert not (tmp_path / "b.db.paygate.key").exists()


@pytest.mark.parametrize("field", ["body", "signature", "previous_hash", "record_hash"])
def test_tamper_locates_record(tmp_path, field):
    db = tmp_path / "t.db"
    ids = _fill(db, 3)
    conn = sqlite3.connect(db)
    if field == "body":
        conn.execute(
            "UPDATE decisions SET body = replace(body, 'ok 1', 'ok X') WHERE record_id = ?", (ids[1],)
        )
    elif field == "signature":
        conn.execute(
            'UPDATE decisions SET body = replace(body, \'"signature":"\', \'"signature":"AAAA\') '
            "WHERE record_id = ?",
            (ids[1],),
        )
    else:
        conn.execute(f"UPDATE decisions SET {field} = ? WHERE record_id = ?", ("f" * 64, ids[1]))
    conn.commit()
    conn.close()
    assert verify_decision_log(db) == ids[1]
    assert chain_status(db)["first_invalid_id"] == ids[1]


def test_deleted_middle_record_flags_next(tmp_path):
    db = tmp_path / "t.db"
    ids = _fill(db, 3)
    conn = sqlite3.connect(db)
    conn.execute("DELETE FROM decisions WHERE record_id = ?", (ids[1],))
    conn.commit()
    conn.close()
    assert verify_decision_log(db) == ids[2]


def test_unknown_key_is_invalid(tmp_path):
    db = tmp_path / "t.db"
    ids = _fill(db, 1)
    (tmp_path / "t.db.paygate.key").unlink()
    conn = sqlite3.connect(db)
    conn.execute("DELETE FROM decision_keys")
    conn.commit()
    conn.close()
    assert verify_decision_log(db) == ids[0]


def test_concurrent_appends_form_single_chain(tmp_path):
    db = tmp_path / "t.db"  # no key yet: threads also race to create it
    errors: list[Exception] = []
    barrier = threading.Barrier(8)

    def work():
        try:
            log = DecisionLog(db)
            barrier.wait()
            for i in range(5):
                log.append(_rec(i))
            log.close()
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=work) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert chain_status(db) == {"valid": True, "first_invalid_id": None, "count": 40}
    conn = sqlite3.connect(db)
    rows = conn.execute("SELECT previous_hash, record_hash FROM decisions ORDER BY seq").fetchall()
    conn.close()
    assert rows[0][0] == ZERO_HASH
    assert all(rows[i][0] == rows[i - 1][1] for i in range(1, len(rows)))
    assert len({r[0] for r in rows}) == 40
    assert not list(tmp_path.glob("*.tmp"))


def test_record_holds_no_content_text(tmp_path):
    db = tmp_path / "t.db"
    log = DecisionLog(db)
    rec = log.append(_rec())
    assert set(rec.model_dump()) == {
        "record_id", "created_at", "decision", "reason_codes", "explanation", "spans",
        "skipped_checks", "request_hash", "previous_hash", "key_id", "signature",
    }  # fmt: skip
    log.close()


def test_decision_markdown_renders_record_without_content(tmp_path):
    from intenttrace.paygate_log import decision_markdown

    log = DecisionLog(tmp_path / "m.db")
    rec = log.append(
        RecordInput(
            decision="BLOCK",
            reason_codes=["INJECTION_DETECTED", "BEST_MATCH_DEVIATION"],
            explanation="N suspicious span(s) found. Technical signal on synthetic data. Not legal advice.",
            spans=[HighlightedSpan(item_id="c0", start=1, end=5, rule_id="r1")],
            request_hash="ab" * 32,
        )
    )
    log.close()
    md = decision_markdown(rec)
    assert f"# Evidence packet: {rec.record_id}" in md
    assert "- Verdict: BLOCK" in md
    assert "- Rule: INJECTION_DETECTED,BEST_MATCH_DEVIATION" in md
    assert "c0[1:5]" in md
    assert "> Technical signal on synthetic data. Not legal advice." in md
    assert "## Decision record" in md
    for value in (rec.request_hash, rec.previous_hash, rec.key_id, rec.signature):
        assert value in md
    assert "content text is not stored" in md


def test_decision_markdown_without_spans(tmp_path):
    from intenttrace.paygate_log import decision_markdown

    log = DecisionLog(tmp_path / "n.db")
    rec = log.append(_rec(1))
    log.close()
    md = decision_markdown(rec)
    assert "- **CLEAN**" in md
    assert "spans: c0[1:5]" in md
