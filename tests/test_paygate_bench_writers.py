"""PayGate benchmark writers (design.md Benchmark Output; Requirements 11.7, 11.8, 11.9, 12.3)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from intenttrace.bench import (
    PAYGATE_BEGIN,
    PAYGATE_END,
    PAYGATE_PIPELINE_NOTICE,
    render_paygate_section,
    write_paygate_results,
    write_results,
)

NOTICE = "Pipeline test on synthetic data. Not a measure of real-world accuracy."


def _rates(n: int, block: float) -> dict:
    return {"n": n, "block_rate": block, "ask_human_rate": 0.1, "allow_rate": 0.9 - block}


def _paygate(provider: str = "fake", pipeline: bool = True, block: float = 0.5) -> dict:
    group = {"n": 4, "block_rate": block}
    return {
        "provider": provider,
        "model": "m-1",
        "seed": 7,
        "n": 10,
        "date": "2025-01-02",
        "pipeline_test_only": pipeline,
        "attack": _rates(6, block),
        "legitimate": _rates(2, 0.0),
        "false_block_rate": 0.0,
        "excluded": {
            "merchant_misrepresentation": {"count": 1, "reason": "The failure appears only after purchase."},
            "payment_only_integrity": {"count": 1, "reason": "Alters only the payment mandate."},
        },
        "block_rate_by_label": {"MANIPULATED": group},
        "block_rate_by_attack_type": {"hidden_instruction": group},
        "block_rate_by_cause": {"price_mismatch": group},
        "latency_ms": {"p50": 1.5, "p95": 3.25},
    }


def _intenttrace_results() -> dict:
    return {"provider": "fake", "model": "fake-1", "n": 3, "marker_key": "kept"}


def _fake_md_results() -> dict:
    metrics = {
        "macro_f1": 1.0,
        "coverage": 1.0,
        "false_accusation_rate": 0.0,
        "latency_ms": {"p50": 1.0, "p95": 2.0},
        "per_verdict": {},
        "confusion_matrix": {},
        "manipulated_recall_by_attack": {},
    }
    return {
        "provider": "fake",
        "model": "fake-1",
        "prompt_version": "v1",
        "seed": 1,
        "n": 3,
        "date": "2025-01-01",
        "pipeline_test_only": True,
        "replay_on": metrics,
        "replay_off": metrics,
        "llm": {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0},
    }


def _write_intenttrace(out: Path) -> None:
    from intenttrace import bench

    # Empty per-verdict tables would KeyError, so build real-looking metrics via compute_metrics.
    rows = [{"true": "LEGITIMATE", "pred": "LEGITIMATE", "attack_type": None}]
    m = bench.compute_metrics(rows)
    m["llm"] = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    m["latency_ms"] = {"p50": 1.0, "p95": 2.0}
    res = _fake_md_results()
    res["replay_on"] = res["replay_off"] = m
    write_results(res, out)


def test_section_written_with_fields_and_tables(tmp_path: Path) -> None:
    _write_intenttrace(tmp_path)
    write_paygate_results(_paygate(), tmp_path)
    md = (tmp_path / "RESULTS.md").read_text(encoding="utf-8")
    assert md.count(PAYGATE_BEGIN) == 1 and md.count(PAYGATE_END) == 1
    for text in ("fake", "m-1", "| Seed | 7 |", "| N (cases) | 10 |", "2025-01-02", "p50 1.5 ms", "p95 3.2"):
        assert text in md
    assert "ASK_HUMAN" in md and "ALLOW" in md and "False-block rate" in md
    assert "hidden_instruction" in md and "price_mismatch" in md and "MANIPULATED" in md
    data = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    assert data["paygate"]["seed"] == 7


def test_section_replaced_in_place_on_rerun(tmp_path: Path) -> None:
    _write_intenttrace(tmp_path)
    write_paygate_results(_paygate(block=0.5), tmp_path)
    write_paygate_results(_paygate(block=0.75), tmp_path)
    md = (tmp_path / "RESULTS.md").read_text(encoding="utf-8")
    assert md.count(PAYGATE_BEGIN) == 1
    assert "75.0%" in md and "blocked 50.0% of attack" not in md


def test_in_place_keeps_text_after_block(tmp_path: Path) -> None:
    md_path = tmp_path / "RESULTS.md"
    md_path.write_text(f"head\n\n{PAYGATE_BEGIN}\nold\n{PAYGATE_END}\n\ntail\n", encoding="utf-8")
    write_paygate_results(_paygate(), tmp_path)
    md = md_path.read_text(encoding="utf-8")
    assert md.startswith("head") and md.rstrip().endswith("tail") and "old" not in md


def test_intenttrace_block_kept_after_write_paygate_results(tmp_path: Path) -> None:
    _write_intenttrace(tmp_path)
    before = (tmp_path / "RESULTS.md").read_text(encoding="utf-8")
    write_paygate_results(_paygate(), tmp_path)
    md = (tmp_path / "RESULTS.md").read_text(encoding="utf-8")
    assert md.startswith(before.rstrip("\n"))
    data = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    assert data["provider"] == "fake" and data["n"] == 3 and "replay_on" in data


def test_paygate_block_and_key_kept_after_write_results(tmp_path: Path) -> None:
    _write_intenttrace(tmp_path)
    write_paygate_results(_paygate(), tmp_path)
    block = render_paygate_section(_paygate())
    _write_intenttrace(tmp_path)
    md = (tmp_path / "RESULTS.md").read_text(encoding="utf-8")
    assert block in md
    assert md.startswith("# IntentTrace benchmark results")
    data = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    assert data["paygate"] == _paygate()


def test_excluded_table_present() -> None:
    section = render_paygate_section(_paygate())
    assert "| Excluded group | Count | Reason |" in section
    assert "| merchant_misrepresentation | 1 | The failure appears only after purchase. |" in section
    assert "| payment_only_integrity | 1 |" in section


@pytest.mark.parametrize("provider", ["none", "fake"])
def test_pipeline_label_present_for_none_and_fake(provider: str) -> None:
    assert PAYGATE_PIPELINE_NOTICE == NOTICE
    assert NOTICE in render_paygate_section(_paygate(provider=provider, pipeline=True))


def test_pipeline_label_absent_for_real_provider() -> None:
    assert NOTICE not in render_paygate_section(_paygate(provider="anthropic", pipeline=False))


def test_rendered_excluded_groups_stay_out_of_rate_tables(tmp_path: Path, monkeypatch) -> None:
    from intenttrace.bench import run_paygate_bench
    from intenttrace.sim.generate import build_cases

    monkeypatch.setenv("INTENTTRACE_DB", str(tmp_path / "user.db"))
    generated = build_cases(40, 7)
    labels = {g.label["case_id"]: g.label for g in generated}
    results = run_paygate_bench([g.case for g in generated], labels, None, seed=7)
    results.update(provider="none", pipeline_test_only=True)
    section = render_paygate_section(results)
    head, _, rest = section.partition("| Excluded group | Count | Reason |")
    excluded_rows = rest.split("\n\n", 1)[0]
    merchant = results["excluded"]["merchant_misrepresentation"]
    payment = results["excluded"]["payment_only_integrity"]
    assert merchant["count"] > 0 and payment["count"] > 0
    assert f"| merchant_misrepresentation | {merchant['count']} | {merchant['reason']} |" in excluded_rows
    assert f"| payment_only_integrity | {payment['count']} | {payment['reason']} |" in excluded_rows
    tables = head + rest.split("\n\n", 1)[1]
    for name in ("MERCHANT_MISREPRESENTATION", "amount_altered", "cart_hash_altered"):
        assert name not in tables
