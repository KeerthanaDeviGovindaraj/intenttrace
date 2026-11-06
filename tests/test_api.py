import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from intenttrace.api import create_app
from intenttrace.cli import app as cli_app
from intenttrace.store import Store, db_path

SAMPLE = Path(__file__).resolve().parent.parent / "benchmark" / "sample"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("INTENTTRACE_DB", str(tmp_path / "t.db"))
    monkeypatch.setenv("INTENTTRACE_RESULTS", str(tmp_path / "results.json"))
    monkeypatch.setenv("INTENTTRACE_WEB_DIST", str(tmp_path / "nodist"))
    return TestClient(create_app())


def _case(name="case-0007"):
    return json.loads((SAMPLE / f"{name}.json").read_text())


def test_db_path_override(monkeypatch):
    monkeypatch.delenv("INTENTTRACE_DB", raising=False)
    assert db_path() == "intenttrace.db"
    monkeypatch.setenv("INTENTTRACE_DB", "x.db")
    assert db_path() == "x.db"


def test_store_roundtrip(tmp_path):
    from intenttrace.models import CaseFile
    from intenttrace.pipeline import investigate

    case = CaseFile.model_validate(_case())
    store = Store(tmp_path / "s.db")
    assert store.get_case(case.case_id) is None
    store.save_case(case, investigate(case, replay=False))
    got_case, got_report = store.get_case(case.case_id)
    assert got_case == case and got_report.case_id == case.case_id
    assert len(store.list_cases()) == 1
    assert store.list_cases("NOPE") == []
    assert store.latest_bench_run() is None
    store.save_bench_run("r1", "{}")
    assert store.latest_bench_run() == "{}"
    store.close()


def test_investigate_and_fetch(client):
    r = client.post("/api/investigate", json=_case())
    assert r.status_code == 200
    body = r.json()
    assert body["case_id"] == "case-0007"
    verdict = body["report"]["verdict"]

    lst = client.get("/api/cases").json()
    assert [c["case_id"] for c in lst] == ["case-0007"]
    assert {"verdict", "confidence", "created_at", "summary"} <= set(lst[0])
    assert client.get("/api/cases", params={"verdict": verdict}).json() == lst
    assert client.get("/api/cases", params={"verdict": "NOPE"}).json() == []

    detail = client.get("/api/cases/case-0007").json()
    assert detail["case"]["case_id"] == "case-0007"
    assert detail["report"]["verdict"] == verdict

    md = client.get("/api/cases/case-0007/evidence.md")
    assert md.status_code == 200
    assert md.headers["content-type"].startswith("text/markdown")
    assert "case-0007" in md.text


def test_unknown_case_404(client):
    assert client.get("/api/cases/nope").status_code == 404
    assert client.get("/api/cases/nope/evidence.md").status_code == 404


def test_invalid_case_422_with_json_paths(client):
    bad = _case()
    del bad["intent"]
    r = client.post("/api/investigate", json=bad)
    assert r.status_code == 422
    paths = [e["path"] for e in r.json()["detail"]]
    assert any(p.startswith("$.intent") for p in paths)
    assert client.post("/api/investigate", content=b"{not json").status_code == 422


def test_benchmark_latest(client, tmp_path):
    assert client.get("/api/benchmark/latest").status_code == 404
    (tmp_path / "results.json").write_text('{"n": 3}')
    assert client.get("/api/benchmark/latest").json() == {"n": 3}


def test_cors_allows_dev_origin(client):
    r = client.get("/api/cases", headers={"Origin": "http://localhost:5173"})
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_serves_dist_when_present(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>dash</html>")
    monkeypatch.setenv("INTENTTRACE_DB", str(tmp_path / "t.db"))
    monkeypatch.setenv("INTENTTRACE_WEB_DIST", str(dist))
    c = TestClient(create_app())
    assert "dash" in c.get("/").text
    assert c.get("/api/cases").json() == []


def test_cli_load_sample(tmp_path, monkeypatch):
    monkeypatch.setenv("INTENTTRACE_DB", str(tmp_path / "t.db"))
    res = CliRunner().invoke(cli_app, ["load-sample", "--dir", str(SAMPLE)])
    assert res.exit_code == 0, res.output
    assert "Stored 12" in res.output
    c = TestClient(create_app())
    assert len(c.get("/api/cases").json()) == 12


def test_cli_serve_help():
    res = CliRunner().invoke(cli_app, ["serve", "--help"])
    assert res.exit_code == 0 and "--port" in res.output
