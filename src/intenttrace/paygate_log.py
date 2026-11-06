"""Signed, hash-chained PayGate decision log (paygate design.md: Decision log, Gate key handling).

The log stores a request hash and span offsets only. Untrusted content text is never written.
"""

from __future__ import annotations

import base64
import hashlib
import os
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import BaseModel, Field

from intenttrace import __version__, crypto
from intenttrace.evidence import EvidencePacket, to_markdown
from intenttrace.models import Finding, Span
from intenttrace.paygate import HighlightedSpan
from intenttrace.store import db_path

ZERO_HASH = "0" * 64
KEY_FILE_ENV = "PAYGATE_KEY_FILE"
BUSY_TIMEOUT_SECONDS = 5

_SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions (
    seq           INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id     TEXT NOT NULL UNIQUE,
    created_at    TEXT NOT NULL,
    decision      TEXT NOT NULL CHECK (decision IN ('ALLOW','BLOCK','ASK_HUMAN')),
    body          TEXT NOT NULL,
    previous_hash TEXT NOT NULL UNIQUE,
    record_hash   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS decisions_decision ON decisions (decision, seq);
CREATE TABLE IF NOT EXISTS decision_keys (
    key_id TEXT PRIMARY KEY, public_key TEXT NOT NULL, created_at TEXT NOT NULL
);
"""


class LogWriteError(Exception):
    """The decision could not be written to the log. Never carries key material."""


class DecisionRecord(BaseModel):
    record_id: str
    created_at: str
    decision: Literal["ALLOW", "BLOCK", "ASK_HUMAN"]
    reason_codes: list[str]
    explanation: str
    spans: list[HighlightedSpan] = Field(default_factory=list)
    skipped_checks: list[str] = Field(default_factory=list)
    request_hash: str
    previous_hash: str
    key_id: str
    signature: str


class RecordInput(BaseModel):
    """What the gate hands to ``DecisionLog.append``."""

    decision: Literal["ALLOW", "BLOCK", "ASK_HUMAN"]
    reason_codes: list[str]
    explanation: str
    spans: list[HighlightedSpan] = Field(default_factory=list)
    skipped_checks: list[str] = Field(default_factory=list)
    request_hash: str


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def key_id_for(public_key_b64: str) -> str:
    return hashlib.sha256(public_key_b64.encode("ascii")).hexdigest()[:16]


def _public_b64(private_key: Ed25519PrivateKey) -> str:
    return base64.b64encode(private_key.public_key().public_bytes_raw()).decode("ascii")


def _read_key(path: Path) -> Ed25519PrivateKey:
    seed = base64.b64decode(path.read_text(encoding="ascii").strip(), validate=True)
    return Ed25519PrivateKey.from_private_bytes(seed)


def _create_key(path: Path) -> Ed25519PrivateKey:
    """Create a new key file atomically with mode 0600. If another writer won the race, load its key.

    The seed is written in full to a private temp file (O_EXCL, 0600), then hard-linked into place.
    ``os.link`` fails if the target exists, so readers never see an empty or partial key file.
    """
    private_key, _ = crypto.generate_keypair()
    seed = private_key.private_bytes_raw()
    tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="ascii") as fh:
            fh.write(base64.b64encode(seed).decode("ascii") + "\n")
        try:
            os.link(tmp, path)
        except FileExistsError:
            return _read_key(path)
        return private_key
    finally:
        tmp.unlink(missing_ok=True)


def _default_key_path(db: str) -> Path:
    return Path(db + ".paygate.key")


class DecisionLog:
    def __init__(self, db: str | Path | None = None, key_file: str | Path | None = None) -> None:
        self.path = str(db) if db is not None else db_path()
        explicit = key_file if key_file is not None else (os.environ.get(KEY_FILE_ENV) or None)
        self._explicit_key = Path(explicit) if explicit is not None else None
        self._key: Ed25519PrivateKey | None = None
        self._conn = sqlite3.connect(
            self.path, timeout=BUSY_TIMEOUT_SECONDS, isolation_level=None, check_same_thread=False
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        self._conn.close()

    def _gate_key(self) -> Ed25519PrivateKey:
        """Load (or, for the default path only, create) the gate key. Raises LogWriteError."""
        if self._key is not None:
            return self._key
        try:
            if self._explicit_key is not None:
                key = _read_key(self._explicit_key)  # never auto-created
            else:
                path = _default_key_path(self.path)
                key = _read_key(path) if path.exists() else _create_key(path)
        except Exception as exc:
            raise LogWriteError(f"gate key unavailable ({type(exc).__name__})") from None
        self._key = key
        return key

    def append(self, result_fields: RecordInput) -> DecisionRecord:
        try:
            key = self._gate_key()
            public = _public_b64(key)
            key_id = key_id_for(public)
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                row = self._conn.execute(
                    "SELECT record_hash FROM decisions ORDER BY seq DESC LIMIT 1"
                ).fetchone()
                previous = row["record_hash"] if row else ZERO_HASH
                now = _now()
                unsigned = DecisionRecord(
                    record_id="dec-" + uuid.uuid4().hex,
                    created_at=now,
                    key_id=key_id,
                    previous_hash=previous,
                    signature="",
                    **result_fields.model_dump(),
                )
                record = unsigned.model_copy(update={"signature": crypto.sign(unsigned, key)})
                self._conn.execute(
                    "INSERT OR IGNORE INTO decision_keys (key_id, public_key, created_at) VALUES (?, ?, ?)",
                    (key_id, public, now),
                )
                self._conn.execute(
                    "INSERT INTO decisions "
                    "(record_id, created_at, decision, body, previous_hash, record_hash) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        record.record_id,
                        record.created_at,
                        record.decision,
                        record.model_dump_json(),
                        record.previous_hash,
                        crypto.mandate_hash(record),
                    ),
                )
                self._conn.execute("COMMIT")
            except BaseException:
                if self._conn.in_transaction:
                    self._conn.execute("ROLLBACK")
                raise
            return record
        except LogWriteError:
            raise
        except Exception as exc:
            raise LogWriteError(f"decision log write failed ({type(exc).__name__})") from None

    def list(self, decision: str | None = None, limit: int = 100) -> list[DecisionRecord]:
        """Records newest first, optionally filtered by decision. ``limit`` is clamped to 1..500."""
        limit = max(1, min(int(limit), 500))
        sql = "SELECT body FROM decisions"
        args: tuple = ()
        if decision:
            sql += " WHERE decision = ?"
            args = (decision,)
        sql += " ORDER BY seq DESC LIMIT ?"
        rows = self._conn.execute(sql, (*args, limit)).fetchall()
        return [DecisionRecord.model_validate_json(r["body"]) for r in rows]

    def get(self, record_id: str) -> DecisionRecord | None:
        row = self._conn.execute("SELECT body FROM decisions WHERE record_id = ?", (record_id,)).fetchone()
        return DecisionRecord.model_validate_json(row["body"]) if row else None


def _trusted_keys(conn: sqlite3.Connection, db: str) -> dict[str, str]:
    """key_id -> public key. A locally available key file is the only trusted key."""
    env = os.environ.get(KEY_FILE_ENV)
    path = Path(env) if env else _default_key_path(db)
    if path.exists():
        try:
            public = _public_b64(_read_key(path))
            return {key_id_for(public): public}
        except Exception:
            return {}
    rows = conn.execute("SELECT key_id, public_key FROM decision_keys").fetchall()
    return {r["key_id"]: r["public_key"] for r in rows}


def _scan(db: str | Path | None) -> tuple[str | None, int]:
    """(first invalid record id or None, record count)."""
    path = str(db) if db is not None else db_path()
    if not Path(path).exists():
        return None, 0
    conn = sqlite3.connect(path, timeout=BUSY_TIMEOUT_SECONDS)
    conn.row_factory = sqlite3.Row
    try:
        try:
            rows = conn.execute(
                "SELECT record_id, decision, previous_hash, record_hash, body FROM decisions ORDER BY seq"
            ).fetchall()
            keys = _trusted_keys(conn, path)
        except sqlite3.OperationalError:
            return None, 0  # no decisions table: empty log
        expected_prev = ZERO_HASH
        for row in rows:
            rid = row["record_id"]
            try:
                record = DecisionRecord.model_validate_json(row["body"])
            except Exception:
                return rid, len(rows)
            public = keys.get(record.key_id)
            ok = (
                record.record_id == rid
                and record.decision == row["decision"]
                and record.previous_hash == row["previous_hash"] == expected_prev
                and crypto.mandate_hash(record) == row["record_hash"]
                and public is not None
                and crypto.verify(record, public)
            )
            if not ok:
                return rid, len(rows)
            expected_prev = row["record_hash"]
        return None, len(rows)
    finally:
        conn.close()


def verify_decision_log(db: str | Path | None = None) -> str | None:
    """ID of the first record with a bad signature or chain link, or None if the log is valid."""
    return _scan(db)[0]


def chain_status(db: str | Path | None = None) -> dict:
    bad, count = _scan(db)
    return {"valid": bad is None, "first_invalid_id": bad, "count": count}


_RECORD_NOTICE = "Technical signal on synthetic data. Not legal advice."


def decision_markdown(record: DecisionRecord) -> str:
    """Markdown evidence for one decision record.

    The log keeps offsets only, so flagged text cannot be rebuilt. Spans appear in findings.
    """
    spans = [
        Span(step_id=s.item_id, start=s.start, end=s.end, rule_id=s.rule_id, method="rule")
        for s in record.spans
    ]
    injection_at = (
        record.reason_codes.index("INJECTION_DETECTED") if "INJECTION_DETECTED" in record.reason_codes else 0
    )
    findings = [
        Finding(
            kind=code,
            detail="Reason code recorded by the gate.",
            step_ids=sorted({s.step_id for s in spans}) if i == injection_at else [],
            spans=spans if i == injection_at else [],
        )
        for i, code in enumerate(record.reason_codes)
    ]
    packet = EvidencePacket(
        case_id=record.record_id,
        verdict=record.decision,
        confidence="n/a",
        rule_id=",".join(record.reason_codes),
        summary=record.explanation,
        findings=findings,
        generated_at=record.created_at,
        tool_version=__version__,
        notice=_RECORD_NOTICE,
    )
    return to_markdown(packet) + "\n".join(
        [
            "",
            "## Decision record",
            "",
            f"- Request hash: {record.request_hash}",
            f"- Previous hash: {record.previous_hash}",
            f"- Key ID: {record.key_id}",
            f"- Signature: {record.signature}",
            "",
            "The log stores a request hash and span offsets only, so the content text is not stored "
            "and no flagged excerpts can be shown.",
            "",
        ]
    )
