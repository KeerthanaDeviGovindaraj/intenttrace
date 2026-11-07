from pathlib import Path

import pytest

from intenttrace.mcp_server import create_server, get_case, investigate_purchase, list_cases

SAMPLE = Path(__file__).resolve().parent.parent / "benchmark" / "sample"


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    monkeypatch.setenv("INTENTTRACE_DB", str(tmp_path / "t.db"))


def test_investigate_get_and_list():
    text = (SAMPLE / "case-0007.json").read_text()
    md = investigate_purchase(text)
    assert isinstance(md, str) and md.strip()
    rows = list_cases()
    assert len(rows) == 1
    cid = rows[0]["case_id"]
    assert get_case(cid)["report"]["verdict"] == rows[0]["verdict"]
    assert list_cases(rows[0]["verdict"]) == rows
    assert list_cases("no_such_verdict") == []


def test_errors():
    with pytest.raises(ValueError):
        investigate_purchase("not json")
    with pytest.raises(ValueError):
        get_case("missing")


def test_invalid_case_schema():
    with pytest.raises(ValueError, match="Invalid case file"):
        investigate_purchase("{}")
    assert list_cases() == []


def test_all_sample_cases_and_verdict_filter():
    paths = sorted(SAMPLE.glob("case-*.json"))
    assert paths
    for p in paths:
        assert investigate_purchase(p.read_text()).strip()
    rows = list_cases()
    assert len(rows) == len(paths)
    verdicts = {r["verdict"] for r in rows}
    assert len(verdicts) > 1
    for v in verdicts:
        filtered = list_cases(v)
        assert filtered and all(r["verdict"] == v for r in filtered)
        assert len(filtered) == sum(1 for r in rows if r["verdict"] == v)


def test_store_shared_with_api():
    from fastapi.testclient import TestClient

    from intenttrace.api import create_app

    client = TestClient(create_app())
    investigate_purchase((SAMPLE / "case-0007.json").read_text())
    cid = list_cases()[0]["case_id"]
    resp = client.get(f"/api/cases/{cid}")
    assert resp.status_code == 200
    assert resp.json()["report"] == get_case(cid)["report"]

    api_text = (SAMPLE / "case-0001.json").read_text()
    posted = client.post("/api/investigate", content=api_text)
    assert posted.status_code == 200
    assert get_case(posted.json()["case_id"])["report"] == posted.json()["report"]


def test_server_registers_tools():
    import asyncio

    server = create_server()
    names = {t.name for t in asyncio.run(server.list_tools())}
    assert names == {"investigate_purchase", "get_case", "list_cases", "check_purchase"}
