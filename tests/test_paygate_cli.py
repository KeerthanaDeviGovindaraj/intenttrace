"""CLI tests for ``intenttrace paygate-bench``."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from intenttrace.cli import app

runner = CliRunner()


def _base(tmp_path, *extra):
    return ["paygate-bench", "--n", "20", "--seed", "3", "--out", str(tmp_path / "out"), *extra]


def test_paygate_bench_writes_results_and_summary(tmp_path, monkeypatch):
    db = tmp_path / "user.db"
    monkeypatch.setenv("INTENTTRACE_DB", str(db))
    result = runner.invoke(app, _base(tmp_path))
    assert result.exit_code == 0, result.output
    assert "Attack block rate" in result.output
    assert "Legitimate false-block rate" in result.output
    assert "pipeline test" in result.output.lower()
    data = json.loads((tmp_path / "out" / "results.json").read_text())
    assert data["paygate"]["n"] == 20 and data["paygate"]["seed"] == 3
    assert data["paygate"]["provider"] == "none"
    md = (tmp_path / "out" / "RESULTS.md").read_text()
    assert "<!-- paygate:begin -->" in md and "<!-- paygate:end -->" in md
    assert not db.exists()


def test_paygate_bench_thresholds_set_exit_code(tmp_path):
    assert (
        runner.invoke(
            app, _base(tmp_path, "--min-block-rate", "0.0", "--max-false-block-rate", "1.0")
        ).exit_code
        == 0
    )
    assert runner.invoke(app, _base(tmp_path, "--min-block-rate", "1.01")).exit_code == 1
    assert runner.invoke(app, _base(tmp_path, "--max-false-block-rate", "-0.1")).exit_code == 1


def test_paygate_bench_fake_provider(tmp_path):
    result = runner.invoke(app, _base(tmp_path, "--provider", "fake"))
    assert result.exit_code == 0, result.output
    assert json.loads((tmp_path / "out" / "results.json").read_text())["paygate"]["provider"] == "fake"


def test_paygate_bench_load_error_exits_2(tmp_path):
    args = [
        "paygate-bench",
        "--cases-dir",
        str(tmp_path / "missing"),
        "--labels",
        str(tmp_path / "missing.jsonl"),
        "--out",
        str(tmp_path / "out"),
    ]
    assert runner.invoke(app, args).exit_code == 2


def test_paygate_bench_unknown_provider_exits_2(tmp_path):
    assert runner.invoke(app, _base(tmp_path, "--provider", "nope")).exit_code == 2


def test_paygate_load_sample_writes_decisions(tmp_path, monkeypatch):
    from intenttrace.paygate_log import DecisionLog, chain_status

    db = tmp_path / "user.db"
    monkeypatch.setenv("INTENTTRACE_DB", str(db))
    monkeypatch.delenv("PAYGATE_KEY_FILE", raising=False)
    res = CliRunner().invoke(app, ["paygate-load-sample"])
    assert res.exit_code == 0, res.output
    assert "Gated 12 sample cases" in res.output
    log = DecisionLog(db)
    try:
        assert {r.decision for r in log.list()} == {"ALLOW", "BLOCK", "ASK_HUMAN"}
    finally:
        log.close()
    assert chain_status(db) == {"valid": True, "first_invalid_id": None, "count": 12}


def test_paygate_load_sample_missing_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("INTENTTRACE_DB", str(tmp_path / "user.db"))
    res = CliRunner().invoke(app, ["paygate-load-sample", "--dir", str(tmp_path / "nope")])
    assert res.exit_code == 2
