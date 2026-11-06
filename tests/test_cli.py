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
