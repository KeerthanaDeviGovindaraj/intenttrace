"""Benchmark metrics, writers and CLI (Req 9, 12.4; design 12)."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from intenttrace.bench import compute_metrics, render_markdown
from intenttrace.cli import app

runner = CliRunner()


def _row(true, pred, attack=None):
    return {"true": true, "pred": pred, "attack_type": attack}


def test_metrics_on_known_rows():
    rows = [
        _row("LEGITIMATE", "LEGITIMATE"),
        _row("LEGITIMATE", "MANIPULATED"),
        _row("LEGITIMATE", "INCONCLUSIVE"),
        _row("MANIPULATED", "MANIPULATED", "hidden_text"),
        _row("MANIPULATED", "LEGITIMATE", "hidden_text"),
        _row("MANIPULATED", "MANIPULATED", "fake_urgency"),
    ]
    m = compute_metrics(rows)
    assert m["coverage"] == 5 / 6
    assert m["false_accusation_rate"] == 1 / 3
    legit = m["per_verdict"]["LEGITIMATE"]
    assert legit["precision"] == 0.5 and legit["recall"] == 1 / 3
    assert m["per_verdict"]["MANIPULATED"]["precision"] == 2 / 3
    assert m["confusion_matrix"]["LEGITIMATE"]["INCONCLUSIVE"] == 1
    assert m["manipulated_recall_by_attack"]["hidden_text"]["recall"] == 0.5
    assert m["manipulated_recall_by_attack"]["fake_urgency"]["recall"] == 1.0
    # Verdicts with no cases contribute F1 = 0 to the macro average over five verdicts.
    assert m["macro_f1"] == sum(v["f1"] for v in m["per_verdict"].values()) / 5


def test_fake_provider_results_labeled_as_pipeline_test():
    results = {
        "provider": "fake",
        "model": "fake-deterministic",
        "prompt_version": "1",
        "seed": 3,
        "n": 0,
        "date": "2025-01-01",
        "pipeline_test_only": True,
        "replay_on": compute_metrics([]) | {"latency_ms": {"p50": 0, "p95": 0}},
        "replay_off": compute_metrics([]) | {"latency_ms": {"p50": 0, "p95": 0}},
        "llm": {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0},
    }
    md = render_markdown(results)
    assert "Pipeline test, not model accuracy" in md
    results["provider"], results["pipeline_test_only"] = "real", False
    assert "not model accuracy" not in render_markdown(results)


def test_bench_n30_smoke_writes_results(tmp_path):
    result = runner.invoke(
        app, ["bench", "--provider", "fake", "--n", "30", "--seed", "1", "--out", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    data = json.loads((tmp_path / "results.json").read_text())
    assert data["n"] == 30 and data["seed"] == 1 and data["provider"] == "fake"
    assert data["replay_on"]["per_verdict"] and data["replay_off"]["confusion_matrix"]
    assert data["llm"]["calls"] > 0
    md = (tmp_path / "RESULTS.md").read_text()
    assert "Pipeline test, not model accuracy" in md and "Prompt version" in md


def test_bench_thresholds_set_exit_code(tmp_path):
    base = ["bench", "--n", "12", "--seed", "1", "--out", str(tmp_path)]
    assert (
        runner.invoke(app, [*base, "--min-macro-f1", "0.0", "--max-false-accusation", "1.0"]).exit_code == 0
    )
    assert runner.invoke(app, [*base, "--min-macro-f1", "1.01"]).exit_code == 1
    assert runner.invoke(app, [*base, "--max-false-accusation", "-0.1"]).exit_code == 1


def test_bench_reads_generated_cases_from_disk(tmp_path):
    gen = tmp_path / "gen"
    assert runner.invoke(app, ["generate", "--n", "12", "--seed", "2", "--out", str(gen)]).exit_code == 0
    args = ["bench", "--cases-dir", str(gen / "cases"), "--labels", str(gen / "labels.jsonl")]
    result = runner.invoke(app, [*args, "--out", str(tmp_path / "res")])
    assert result.exit_code == 0, result.output
    assert json.loads((tmp_path / "res" / "results.json").read_text())["n"] == 12


def test_bench_rejects_unknown_provider(tmp_path):
    result = runner.invoke(app, ["bench", "--provider", "nope", "--n", "6", "--out", str(tmp_path)])
    assert result.exit_code == 2


def test_generate_writes_manifest_and_bench_reads_seed(tmp_path):
    import json

    gen = tmp_path / "gen"
    assert runner.invoke(app, ["generate", "--n", "6", "--seed", "5", "--out", str(gen)]).exit_code == 0
    manifest = json.loads((gen / "manifest.json").read_text(encoding="utf-8"))
    assert (manifest["seed"], manifest["n"]) == (5, 6) and manifest["generated_at"]
    args = ["bench", "--cases-dir", str(gen / "cases"), "--labels", str(gen / "labels.jsonl")]
    assert runner.invoke(app, [*args, "--out", str(tmp_path / "a")]).exit_code == 0
    assert json.loads((tmp_path / "a" / "results.json").read_text(encoding="utf-8"))["seed"] == 5
    assert runner.invoke(app, [*args, "--seed", "9", "--out", str(tmp_path / "b")]).exit_code == 0
    assert json.loads((tmp_path / "b" / "results.json").read_text(encoding="utf-8"))["seed"] == 9
