"""Tests for the check_purchase MCP tool."""

from __future__ import annotations

import asyncio
import json

import pytest
from conftest import make_case_file

from intenttrace.mcp_server import check_purchase, create_server
from intenttrace.paygate import gate_purchase
from intenttrace.paygate_log import DecisionLog


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    monkeypatch.setenv("INTENTTRACE_DB", str(tmp_path / "t.db"))
    monkeypatch.delenv("INTENTTRACE_LLM_PROVIDER", raising=False)


def _request() -> dict:
    case, _ = make_case_file()
    return {
        "public_keys": case.public_keys,
        "intent": case.intent.model_dump(),
        "cart": case.cart.model_dump(),
        "content": [],
    }


def _count() -> int:
    log = DecisionLog()
    try:
        return log._conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]
    finally:
        log.close()


def test_valid_request_returns_json_dict_and_logs_one_record():
    out = check_purchase(json.dumps(_request()))
    assert isinstance(out, dict)
    json.dumps(out)
    assert out["decision"] == "ALLOW" and out["reason_codes"] == ["CLEAN"]
    assert out["record_id"]
    assert _count() == 1


@pytest.mark.parametrize("text", ["not json", "", "{", "null", "[]"])
def test_unparseable_input_is_malformed_and_logged(text):
    out = check_purchase(text)
    assert out["decision"] == "ASK_HUMAN" and out["reason_codes"] == ["INPUT_MALFORMED"]
    assert out["record_id"]
    assert _count() == 1


def test_matches_python_function():
    raw = _request()
    via_tool = check_purchase(json.dumps(raw))
    direct = gate_purchase(raw, None, replay=True).model_dump(mode="json")
    for d in (via_tool, direct):
        d.pop("record_id")
    assert via_tool == direct
    assert _count() == 2


def test_server_lists_four_tools():
    names = {t.name for t in asyncio.run(create_server().list_tools())}
    assert names == {"investigate_purchase", "get_case", "list_cases", "check_purchase"}
