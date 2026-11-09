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
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from intenttrace.llm.base import LLMProvider
from intenttrace.llm.prompts import PROMPT_VERSION
from intenttrace.models import CaseFile
from intenttrace.paygate import ContentItem, GateRequest, gate_purchase
from intenttrace.paygate_log import DecisionLog
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
    """Build a provider by name (``fake``, ``anthropic`` or ``openai``)."""
    from intenttrace.llm.factory import make_provider as _make

    return _make(name)


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


PAYGATE_DECISIONS = ("BLOCK", "ASK_HUMAN", "ALLOW")
_PAYMENT_ONLY_CAUSES = frozenset({"amount_altered", "cart_hash_altered"})
_PAYGATE_SOURCES = {"merchant": "merchant", "review": "review", "external_agent": "external_agent"}
EXCLUDED_REASONS = {
    "merchant_misrepresentation": "The failure appears only after purchase.",
    "payment_only_integrity": (
        "These causes alter only the payment mandate, which does not exist before payment."
    ),
}


def case_to_request(case: CaseFile) -> GateRequest:
    """Pre-purchase view of a case: no payment, delivered item or listing_after."""
    content = [
        ContentItem(
            item_id=step.step_id,
            source=_PAYGATE_SOURCES[step.source],  # type: ignore[arg-type]
            text=step.content,
            product_id=step.product_id,
        )
        for step in case.trace
        if step.source in _PAYGATE_SOURCES
    ]
    return GateRequest(
        public_keys=case.public_keys,
        intent=case.intent,
        cart=case.cart,
        content=content,
        listings=list(case.listings_at_purchase) or None,
        agent_config=case.agent_config,
    )


def _paygate_group(label: dict) -> str:
    kind, cause = label["label"], label.get("cause")
    if kind == "MERCHANT_MISREPRESENTATION":
        return "merchant_misrepresentation"
    if kind == "INTEGRITY_FAILURE" and cause in _PAYMENT_ONLY_CAUSES:
        return "payment_only_integrity"
    if kind == "LEGITIMATE":
        return "legitimate"
    return "attack"


def _decision_rates(rows: list[dict]) -> dict:
    n = len(rows)
    out: dict = {"n": n}
    for d in PAYGATE_DECISIONS:
        out[f"{d.lower()}_rate"] = _ratio(sum(1 for r in rows if r["decision"] == d), n)
    return out


def _block_rate_by(rows: list[dict], key: str) -> dict[str, dict]:
    groups: dict[str, list[dict]] = {}
    for r in rows:
        if r[key]:
            groups.setdefault(r[key], []).append(r)
    return {
        k: {"n": len(v), "block_rate": _ratio(sum(1 for r in v if r["decision"] == "BLOCK"), len(v))}
        for k, v in sorted(groups.items())
    }


def run_paygate_bench(
    cases: list[CaseFile],
    labels: dict[str, dict],
    provider: LLMProvider | None,
    seed: int | None = None,
    now: datetime | None = None,
) -> dict:
    """Run every case through the pre-purchase gate using a temporary decision log."""
    missing = [c.case_id for c in cases if c.case_id not in labels]
    if missing:
        raise ValueError(f"No label for case(s): {', '.join(missing[:5])}")
    when = now or datetime.now(UTC)
    rows: list[dict] = []
    latencies_ms: list[float] = []
    with tempfile.TemporaryDirectory(prefix="paygate-bench-") as tmp:
        # An explicit key file is never auto-created, so make one in the temp dir. It also
        # overrides PAYGATE_KEY_FILE, so the user's key is never touched.
        _seed_key(Path(tmp) / "bench.key")
        log = DecisionLog(Path(tmp) / "bench.db", Path(tmp) / "bench.key")
        try:
            for case in cases:
                label = labels[case.case_id]
                request = case_to_request(case)
                start = time.perf_counter()
                result = gate_purchase(request, provider, log=log)
                latencies_ms.append((time.perf_counter() - start) * 1000)
                rows.append(
                    {
                        "group": _paygate_group(label),
                        "label": label["label"],
                        "attack_type": label.get("attack_type"),
                        "cause": label.get("cause"),
                        "decision": result.decision,
                    }
                )
        finally:
            log.close()

    attack = [r for r in rows if r["group"] == "attack"]
    legit = [r for r in rows if r["group"] == "legitimate"]
    excluded = {
        name: {"count": sum(1 for r in rows if r["group"] == name), "reason": reason}
        for name, reason in EXCLUDED_REASONS.items()
    }
    legit_rates = _decision_rates(legit)
    return {
        "provider": provider.name if provider else "none",
        "model": provider.model if provider else "none",
        "seed": seed,
        "n": len(cases),
        "date": when.strftime("%Y-%m-%d"),
        "pipeline_test_only": provider is None or provider.name == "fake",
        "attack": _decision_rates(attack),
        "legitimate": legit_rates,
        "false_block_rate": legit_rates["block_rate"],
        "excluded": excluded,
        "block_rate_by_label": _block_rate_by(attack, "label"),
        "block_rate_by_attack_type": _block_rate_by(attack, "attack_type"),
        "block_rate_by_cause": _block_rate_by(attack, "cause"),
        "latency_ms": {"p50": _percentile(latencies_ms, 50), "p95": _percentile(latencies_ms, 95)},
    }


def _seed_key(path: Path) -> None:
    """Create a gate key at ``path`` (inside the benchmark's temporary directory only)."""
    from intenttrace.paygate_log import _create_key

    _create_key(path)


def read_manifest_seed(manifest_path: Path) -> int | None:
    """Seed recorded by ``intenttrace generate``; None when the manifest is missing or unreadable."""
    try:
        seed = json.loads(manifest_path.read_text(encoding="utf-8")).get("seed")
    except (OSError, ValueError, AttributeError):
        return None
    return seed if isinstance(seed, int) and not isinstance(seed, bool) else None


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


PAYGATE_BEGIN = "<!-- paygate:begin -->"
PAYGATE_END = "<!-- paygate:end -->"
PAYGATE_PIPELINE_NOTICE = "Pipeline test on synthetic data. Not a measure of real-world accuracy."


def render_paygate_section(results: dict) -> str:
    """Markdown for the PayGate benchmark, wrapped in the begin/end markers."""
    seed = results["seed"] if results.get("seed") is not None else "unknown"
    attack, legit = results["attack"], results["legitimate"]
    lines = [PAYGATE_BEGIN, "## PayGate benchmark (pre-purchase gate)", ""]
    if results.get("pipeline_test_only"):
        lines += [f"> **{PAYGATE_PIPELINE_NOTICE}**", ""]
    lines += [
        "| Field | Value |",
        "|---|---|",
        f"| Provider | {results['provider']} |",
        f"| Model | {results['model']} |",
        f"| Seed | {seed} |",
        f"| N (cases) | {results['n']} |",
        f"| Date | {results['date']} |",
        "",
        f"**Headline: PayGate blocked {_pct(attack['block_rate'])} of attack cases "
        f"(n={attack['n']}) and {_pct(legit['block_rate'])} of legitimate cases (n={legit['n']}).**",
        "",
        "| Group | N | BLOCK | ASK_HUMAN | ALLOW |",
        "|---|---|---|---|---|",
    ]
    for name, g in (("Attack", attack), ("Legitimate", legit)):
        lines.append(
            f"| {name} | {g['n']} | {_pct(g['block_rate'])} | {_pct(g['ask_human_rate'])} "
            f"| {_pct(g['allow_rate'])} |"
        )
    lines += ["", f"False-block rate (legitimate cases blocked): {_pct(results['false_block_rate'])}", ""]
    for title, key in (
        ("Block rate by label", "block_rate_by_label"),
        ("Block rate by attack type", "block_rate_by_attack_type"),
        ("Block rate by cause", "block_rate_by_cause"),
    ):
        lines += [f"{title}:", "", "| Group | N | Block rate |", "|---|---|---|"]
        for name, e in results[key].items():
            lines.append(f"| {name} | {e['n']} | {_pct(e['block_rate'])} |")
        lines.append("")
    lat = results["latency_ms"]
    lines += [
        f"Latency per decision: p50 {lat['p50']:.1f} ms, p95 {lat['p95']:.1f} ms",
        "",
        "Excluded from every rate above:",
        "",
        "| Excluded group | Count | Reason |",
        "|---|---|---|",
    ]
    for name, e in results["excluded"].items():
        lines.append(f"| {name} | {e['count']} | {e['reason']} |")
    lines += ["", PAYGATE_END]
    return "\n".join(lines)


def _extract_paygate_block(text: str) -> str | None:
    start = text.find(PAYGATE_BEGIN)
    end = text.find(PAYGATE_END, start + 1) if start != -1 else -1
    if start == -1 or end == -1:
        return None
    return text[start : end + len(PAYGATE_END)]


def _merge_paygate_block(text: str, block: str) -> str:
    """Replace the existing PayGate block in place, or append it when absent."""
    start = text.find(PAYGATE_BEGIN)
    end = text.find(PAYGATE_END, start + 1) if start != -1 else -1
    if start != -1 and end != -1:
        return text[:start] + block + text[end + len(PAYGATE_END) :]
    return text.rstrip("\n") + "\n\n" + block + "\n" if text.strip() else block + "\n"


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _read_json_object(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_paygate_results(results: dict, out_dir: Path) -> None:
    """Add the PayGate section to ``RESULTS.md`` and the ``paygate`` key to ``results.json``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path, md_path = out_dir / "results.json", out_dir / "RESULTS.md"
    data = _read_json_object(json_path)
    data["paygate"] = results
    json_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(
        _merge_paygate_block(_read_text(md_path), render_paygate_section(results)), encoding="utf-8"
    )


def write_results(results: dict, out_dir: Path) -> tuple[Path, Path]:
    """Write ``results.json`` and ``RESULTS.md`` under ``out_dir``, keeping any PayGate output."""
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path, md_path = out_dir / "results.json", out_dir / "RESULTS.md"
    old_paygate = _read_json_object(json_path).get("paygate")
    old_block = _extract_paygate_block(_read_text(md_path))
    data = dict(results)
    if old_paygate is not None and "paygate" not in data:
        data["paygate"] = old_paygate
    json_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md = render_markdown(results)
    if old_block:
        md = _merge_paygate_block(md, old_block)
    md_path.write_text(md, encoding="utf-8")
    return json_path, md_path
