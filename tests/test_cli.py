"""CLI tests (Requirements 8.7)."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from intenttrace.cli import app

runner = CliRunner()


def test_generate_writes_cases_and_prints_summary(tmp_path):
    out = tmp_path / "bench"
    result = runner.invoke(app, ["generate", "--n", "12", "--seed", "7", "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert "Generated 12 cases" in result.output
    assert len(list((out / "cases").glob("case-*.json"))) == 12
    labels = [json.loads(line) for line in (out / "labels.jsonl").read_text().splitlines()]
    assert len(labels) == 12
    for label in {entry["label"] for entry in labels}:
        assert f"{label}:" in result.output


def _generated_case(tmp_path, label=None):
    out = tmp_path / "bench"
    result = runner.invoke(app, ["generate", "--n", "12", "--seed", "7", "--out", str(out)])
    assert result.exit_code == 0, result.output
    labels = [json.loads(line) for line in (out / "labels.jsonl").read_text().splitlines()]
    entry = next(e for e in labels if label is None or e["label"] == label)
    return out / "cases" / f"{entry['case_id']}.json", entry["label"]


def test_investigate_prints_verdict_and_packet(tmp_path):
    case_path, _ = _generated_case(tmp_path)
    result = runner.invoke(app, ["investigate", str(case_path), "--no-replay"])
    assert result.exit_code == 0, result.output
    assert "Verdict:" in result.output
    assert "Confidence:" in result.output
    assert "Rule:" in result.output
    assert "Summary:" in result.output
    assert "# Evidence packet:" in result.output


def test_investigate_writes_markdown_to_out(tmp_path):
    case_path, _ = _generated_case(tmp_path)
    report = tmp_path / "report.md"
    result = runner.invoke(app, ["investigate", str(case_path), "--out", str(report)])
    assert result.exit_code == 0, result.output
    assert report.read_text().startswith("# Evidence packet:")
    assert "# Evidence packet:" not in result.output
    assert "Verdict:" in result.output


def test_investigate_invalid_case_exits_2_with_json_paths(tmp_path):
    case_path, _ = _generated_case(tmp_path)
    data = json.loads(case_path.read_text())
    del data["intent"]["natural_language"]
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(data))
    result = runner.invoke(app, ["investigate", str(bad)])
    assert result.exit_code == 2
    assert "$.intent.natural_language" in result.output


def test_investigate_missing_file_and_bad_json_exit_2(tmp_path):
    assert runner.invoke(app, ["investigate", str(tmp_path / "nope.json")]).exit_code == 2
    broken = tmp_path / "broken.json"
    broken.write_text("{not json")
    assert runner.invoke(app, ["investigate", str(broken)]).exit_code == 2


def test_investigate_unknown_provider_exits_2(tmp_path, monkeypatch):
    case_path, _ = _generated_case(tmp_path)
    monkeypatch.setenv("INTENTTRACE_LLM_PROVIDER", "nonesuch")
    assert runner.invoke(app, ["investigate", str(case_path)]).exit_code == 2
