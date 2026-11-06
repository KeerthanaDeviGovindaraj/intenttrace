"""SQLite storage for cases, reports and benchmark runs (design.md section 13)."""

from __future__ import annotations

import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from intenttrace.models import CaseFile
from intenttrace.pipeline import Report

DEFAULT_DB = "intenttrace.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS cases   (case_id TEXT PRIMARY KEY, body TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS reports (case_id TEXT PRIMARY KEY, verdict TEXT NOT NULL, confidence TEXT NOT NULL,
                                    body TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS bench_runs (run_id TEXT PRIMARY KEY, body TEXT NOT NULL, created_at TEXT NOT NULL);
"""


def db_path() -> str:
    """Database path: ``INTENTTRACE_DB`` if set, else ``intenttrace.db``."""
    return os.environ.get("INTENTTRACE_DB") or DEFAULT_DB


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = str(path) if path is not None else db_path()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def save_case(self, case: CaseFile, report: Report) -> None:
        """Store (or replace) a case and its report."""
        now = _now()
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO cases (case_id, body, created_at) VALUES (?, ?, ?)",
                (case.case_id, case.model_dump_json(), now),
            )
            self._conn.execute(
                "INSERT OR REPLACE INTO reports (case_id, verdict, confidence, body, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (case.case_id, str(report.verdict), str(report.confidence), report.model_dump_json(), now),
            )

    def get_case(self, case_id: str) -> tuple[CaseFile, Report] | None:
        row = self._conn.execute(
            "SELECT c.body AS cbody, r.body AS rbody FROM cases c JOIN reports r USING (case_id) "
            "WHERE c.case_id = ?",
            (case_id,),
        ).fetchone()
        if row is None:
            return None
        return CaseFile.model_validate_json(row["cbody"]), Report.model_validate_json(row["rbody"])

    def list_cases(self, verdict: str | None = None) -> list[dict]:
        """Rows of ``{case_id, verdict, confidence, created_at}``, newest first."""
        sql = "SELECT case_id, verdict, confidence, created_at FROM reports"
        args: tuple = ()
        if verdict:
            sql += " WHERE verdict = ?"
            args = (verdict,)
        sql += " ORDER BY created_at DESC, case_id"
        return [dict(r) for r in self._conn.execute(sql, args).fetchall()]

    def save_bench_run(self, run_id: str, body: str) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO bench_runs (run_id, body, created_at) VALUES (?, ?, ?)",
                (run_id, body, _now()),
            )

    def latest_bench_run(self) -> str | None:
        row = self._conn.execute(
            "SELECT body FROM bench_runs ORDER BY created_at DESC, rowid DESC LIMIT 1"
        ).fetchone()
        return row["body"] if row else None
