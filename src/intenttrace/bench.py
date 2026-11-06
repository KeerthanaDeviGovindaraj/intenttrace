"""Benchmark scoring (design.md section 12, Requirements 9 and 12.4).

``run_bench`` investigates every labeled case twice (replay on, then replay off), compares verdicts
with ground truth and computes per-verdict precision/recall/F1, macro F1 over the five decidable
verdicts, a confusion matrix that includes INCONCLUSIVE, coverage, false accusation rate, MANIPULATED
recall by attack type, LLM usage and p50/p95 latency. ``write_results`` writes results.json and
RESULTS.md.
"""

from __future__ import annotations

import json
import math
import time
from datetime import UTC, datetime
from pathlib import Path

from intenttrace.llm.base import LLMProvider
from intenttrace.llm.prompts import PROMPT_VERSION
from intenttrace.models import CaseFile
from intenttrace.pipeline import investigate

DECIDABLE = (
    "LEGITIMATE",
    "MANIPULATED",
    "OUT_OF_SCOPE",
    "MERCHANT_MISREPRESENTATION",
    "INTEGRITY_FAILURE",
)
PREDICTED = (*DECIDABLE, "INCONCLUSIVE")
ACCUSING = frozenset(DECIDABLE) - {"LEGITIMATE"}

FAKE_NOTICE = (
    "These numbers come from the deterministic `fake` provider. They test the pipeline, not model accuracy."
)


def make_provider(name: str) -> LLMProvider:
    """Build a provider by name. Only ``fake`` exists until task 13."""
    if name == "fake":
        from intenttrace.llm.fake import FakeProvider

        return FakeProvider()
    raise ValueError(f"Unsupported provider: {name!r} (only 'fake' is available)")


def _percentile(values: list[float], pct: float) -> float:
    """Nearest-rank percentile; 0.0 for an empty list."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, math.ceil(pct / 100 * len(ordered)))
    return ordered[rank - 1]


def _ratio(num: float, den: float) -> float:
    return num / den if den else 0.0


def compute_metrics(rows: list[dict]) -> dict:
    """Metrics from rows of ``{true, pred, attack_type}``."""
    confusion = {t: {p: 0 for p in PREDICTED} for t in DECIDABLE}
    for r in rows:
        confusion[r["true"]][r["pred"]] += 1

    per_verdict: dict[str, dict] = {}
    for v in DECIDABLE:
        tp = confusion[v][v]
        support = sum(confusion[v].values())
        predicted = sum(confusion[t][v] for t in DECIDABLE)
        precision, recall = _ratio(tp, predicted), _ratio(tp, support)
        per_verdict[v] = {
            "precision": precision,
            "recall": recall,
            "f1": _ratio(2 * precision * recall, precision + recall),
            "support": support,
        }

    total = len(rows)
    inconclusive = sum(1 for r in rows if r["pred"] == "INCONCLUSIVE")
    legit = [r for r in rows if r["true"] == "LEGITIMATE"]
    accused = sum(1 for r in legit if r["pred"] in ACCUSING)

    by_attack: dict[str, dict] = {}
    for r in rows:
        if r["true"] == "MANIPULATED" and r["attack_type"]:
            entry = by_attack.setdefault(r["attack_type"], {"support": 0, "caught": 0})
            entry["support"] += 1
            entry["caught"] += r["pred"] == "MANIPULATED"
    for entry in by_attack.values():
        entry["recall"] = _ratio(entry["caught"], entry["support"])

    return {
        "n": total,
        "per_verdict": per_verdict,
        "macro_f1": _ratio(sum(v["f1"] for v in per_verdict.values()), len(DECIDABLE)),
        "confusion_matrix": confusion,
        "coverage": _ratio(total - inconclusive, total),
        "false_accusation_rate": _ratio(accused, len(legit)),
        "manipulated_recall_by_attack": dict(sorted(by_attack.items())),
    }


def _run_pass(cases: list[CaseFile], labels: dict[str, dict], provider: LLMProvider, replay: bool) -> dict:
    rows: list[dict] = []
    latencies_ms: list[float] = []
    calls0 = provider.usage.calls
    in0, out0, cost0 = provider.usage.input_tokens, provider.usage.output_tokens, provider.usage.cost_usd
    for case in cases:
        start = time.perf_counter()
        report = investigate(case, replay=replay, provider=provider)
        latencies_ms.append((time.perf_counter() - start) * 1000)
        label = labels[case.case_id]
        rows.append({"true": label["label"], "pred": report.verdict, "attack_type": label.get("attack_type")})
    metrics = compute_metrics(rows)
    metrics["llm"] = {
        "calls": provider.usage.calls - calls0,
        "input_tokens": provider.usage.input_tokens - in0,
        "output_tokens": provider.usage.output_tokens - out0,
        "cost_usd": provider.usage.cost_usd - cost0,
    }
    metrics["latency_ms"] = {
        "p50": _percentile(latencies_ms, 50),
        "p95": _percentile(latencies_ms, 95),
    }
    return metrics


def run_bench(
    cases: list[CaseFile],
    labels: dict[str, dict],
    provider: LLMProvider,
    seed: int | None = None,
    now: datetime | None = None,
) -> dict:
    """Run the benchmark with replay on and off. ``labels`` maps case_id to its label entry."""
    missing = [c.case_id for c in cases if c.case_id not in labels]
    if missing:
        raise ValueError(f"No label for case(s): {', '.join(missing[:5])}")
    when = now or datetime.now(UTC)
    replay_on = _run_pass(cases, labels, provider, replay=True)
    replay_off = _run_pass(cases, labels, provider, replay=False)
    return {
        "provider": provider.name,
        "model": provider.model,
        "prompt_version": PROMPT_VERSION,
        "seed": seed,
        "n": len(cases),
        "date": when.strftime("%Y-%m-%d"),
        "pipeline_test_only": provider.name == "fake",
        "replay_on": replay_on,
        "replay_off": replay_off,
        "llm": {
            "calls": provider.usage.calls,
            "input_tokens": provider.usage.input_tokens,
            "output_tokens": provider.usage.output_tokens,
            "cost_usd": provider.usage.cost_usd,
        },
    }


def load_cases(cases_dir: Path, labels_path: Path) -> tuple[list[CaseFile], dict[str, dict]]:
    """Load cases and labels written by ``intenttrace generate``."""
    labels: dict[str, dict] = {}
    for line in labels_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            entry = json.loads(line)
            labels[entry["case_id"]] = entry
    paths = sorted(cases_dir.glob("case-*.json"))
    if not paths:
        raise FileNotFoundError(f"No cases found in {cases_dir}")
    cases = [CaseFile.model_validate_json(p.read_text(encoding="utf-8")) for p in paths]
    return cases, labels


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def _metrics_section(title: str, m: dict) -> list[str]:
    lines = [f"## {title}", ""]
    lines += [
        f"- Macro F1 (5 decidable verdicts): **{m['macro_f1']:.3f}**",
        f"- Coverage (not INCONCLUSIVE): {_pct(m['coverage'])}",
        f"- False accusation rate: {_pct(m['false_accusation_rate'])}",
        f"- Latency per case: p50 {m['latency_ms']['p50']:.1f} ms, p95 {m['latency_ms']['p95']:.1f} ms",
        "",
        "| Verdict | Precision | Recall | F1 | Support |",
        "|---|---|---|---|---|",
    ]
    for v in DECIDABLE:
        pv = m["per_verdict"][v]
        lines.append(
            f"| {v} | {pv['precision']:.3f} | {pv['recall']:.3f} | {pv['f1']:.3f} | {pv['support']} |"
        )
    lines += ["", "Confusion matrix (rows: ground truth, columns: predicted):", ""]
    lines.append("| Truth \\ Predicted | " + " | ".join(PREDICTED) + " |")
    lines.append("|---|" + "---|" * len(PREDICTED))
    for t in DECIDABLE:
        lines.append(f"| {t} | " + " | ".join(str(m["confusion_matrix"][t][p]) for p in PREDICTED) + " |")
    lines += ["", "MANIPULATED recall by attack type:", ""]
    lines += ["| Attack type | Caught | Support | Recall |", "|---|---|---|---|"]
    for attack, e in m["manipulated_recall_by_attack"].items():
        lines.append(f"| {attack} | {e['caught']} | {e['support']} | {e['recall']:.3f} |")
    lines.append("")
    return lines


def render_markdown(results: dict) -> str:
    seed = results["seed"] if results["seed"] is not None else "unknown"
    lines = ["# IntentTrace benchmark results", ""]
    if results["pipeline_test_only"]:
        lines += [f"> **Pipeline test, not model accuracy.** {FAKE_NOTICE}", ""]
    lines += [
        "| Field | Value |",
        "|---|---|",
        f"| Provider | {results['provider']} |",
        f"| Model | {results['model']} |",
        f"| Prompt version | {results['prompt_version']} |",
        f"| Seed | {seed} |",
        f"| N (cases) | {results['n']} |",
        f"| Date | {results['date']} |",
        "",
    ]
    lines += _metrics_section("Replay enabled", results["replay_on"])
    lines += _metrics_section("Replay disabled", results["replay_off"])
    llm = results["llm"]
    lines += [
        "## LLM usage (both passes)",
        "",
        f"- Calls: {llm['calls']}",
        f"- Input tokens: {llm['input_tokens']}",
        f"- Output tokens: {llm['output_tokens']}",
        f"- Estimated cost: ${llm['cost_usd']:.4f}",
        "",
    ]
    return "\n".join(lines)


def write_results(results: dict, out_dir: Path) -> tuple[Path, Path]:
    """Write ``results.json`` and ``RESULTS.md`` under ``out_dir``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path, md_path = out_dir / "results.json", out_dir / "RESULTS.md"
    json_path.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(results), encoding="utf-8")
    return json_path, md_path
