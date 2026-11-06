"""Evidence packet (design.md section 9).

Turns a pipeline ``Report`` plus its ``CaseFile`` into a factual, plain-English packet rendered as
JSON or Markdown. Summaries come from fixed per-verdict templates (no LLM). The packet states
technical findings only and never draws liability conclusions.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from intenttrace import __version__
from intenttrace.forensics.replay import ReplayResult
from intenttrace.models import CaseFile, Finding, Span
from intenttrace.pipeline import Report

NOTICE = (
    "This report describes technical findings from synthetic test data. "
    "It is not legal advice and does not determine liability."
)
MAX_EXCERPT_CHARS = 200
_CONTEXT_CHARS = 60


class IntentCartRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    intent: str
    cart: str
    match: bool


class FlaggedExcerpt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_id: str
    source: str
    start: int
    end: int
    text: str  # flagged text with surrounding context, at most MAX_EXCERPT_CHARS characters
    rule_id: str | None = None
    reason: str | None = None
    method: str | None = None


class EvidencePacket(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    verdict: str
    confidence: str
    rule_id: str
    summary: str
    findings: list[Finding] = Field(default_factory=list)
    secondary_findings: list[Finding] = Field(default_factory=list)
    intent_vs_cart: list[IntentCartRow] = Field(default_factory=list)
    flagged_excerpts: list[FlaggedExcerpt] = Field(default_factory=list)
    replay: ReplayResult | None = None
    generated_at: str
    tool_version: str
    notice: str = NOTICE


# --- summaries -----------------------------------------------------------------------------------


def _first_detail(report: Report) -> str:
    for f in report.findings:
        if f.detail:
            return f.detail.rstrip(".")
    return ""


def _summary(report: Report) -> str:
    v = report.verdict
    conf = report.confidence
    detail = _first_detail(report)
    replay = report.replay
    if v == "INTEGRITY_FAILURE":
        s = (
            f"The mandate chain failed {len(report.findings)} integrity check(s), so the record "
            "cannot be relied on as submitted."
        )
        if detail:
            s += f" First failure: {detail}."
        return s + " Later analysis stages were not run."
    if v == "OUT_OF_SCOPE":
        s = (
            f"The cart or payment exceeded the limits set in the signed intent mandate "
            f"({len(report.findings)} violation(s))."
        )
        if detail:
            s += f" First violation: {detail}."
        return s + " Later analysis stages were not run."
    if v == "MERCHANT_MISREPRESENTATION":
        s = (
            f"The delivered item or later listing differs from the listing shown at purchase "
            f"in {len(report.findings)} material way(s)."
        )
        if detail:
            s += f" First difference: {detail}."
        return s + " Later analysis stages were not run."
    if v == "MANIPULATED":
        n = len(report.detection_spans)
        s = f"{n} span(s) of untrusted content were flagged in the agent's trace."
        if replay and replay.result == "changed":
            s += (
                f" When they were removed and the decision was replayed, the agent chose "
                f"{replay.replay_product_id} instead of {replay.original_product_id}."
            )
        else:
            s += " The purchase differs from the top-ranked eligible product and the influence score is high."
        return s + f" Confidence is {conf}."
    if v == "LEGITIMATE":
        s = "The mandate chain, scope and listing checks found no problems."
        if replay and replay.result == "unchanged":
            s += " Replaying the decision without flagged content produced the same choice."
        elif report.detection_spans:
            s += " Some flagged content was present, but the purchase is not explained by it."
        else:
            s += " No untrusted content was flagged and the choice matches the top-ranked product."
        if conf == "low":
            s += " The choice differs from the best match, but no cause was found."
        return s + f" Confidence is {conf}."
    return (
        "The available evidence did not meet the criteria for any other verdict. "
        "Flagged content, ranking deviation and replay results were mixed or unavailable. "
        "Manual review of the findings below is needed."
    )


# --- tables and excerpts -------------------------------------------------------------------------


def _money(cents: int | None) -> str:
    return "none" if cents is None else f"${cents / 100:.2f}"


def _list(values: list[str] | None) -> str:
    return "any" if values is None else ", ".join(sorted(values)) or "none"


def intent_vs_cart(case: CaseFile) -> list[IntentCartRow]:
    """Compare each intent constraint with what the cart contains."""
    c = case.intent.constraints
    cart = case.cart
    rows: list[IntentCartRow] = []

    total_ok = c.max_total_cents is None or cart.total_cents <= c.max_total_cents
    rows.append(
        IntentCartRow(
            field="total",
            intent=f"max {_money(c.max_total_cents)}",
            cart=_money(cart.total_cents),
            match=total_ok,
        )
    )
    if c.max_unit_price_cents is not None:
        top = max((i.unit_price_cents for i in cart.items), default=0)
        rows.append(
            IntentCartRow(
                field="unit price",
                intent=f"max {_money(c.max_unit_price_cents)}",
                cart=_money(top),
                match=top <= c.max_unit_price_cents,
            )
        )
    if c.max_quantity is not None:
        qty = sum(i.quantity for i in cart.items)
        rows.append(
            IntentCartRow(
                field="quantity", intent=f"max {c.max_quantity}", cart=str(qty), match=qty <= c.max_quantity
            )
        )
    if c.allowed_categories is not None:
        cats = sorted({i.category for i in cart.items})
        rows.append(
            IntentCartRow(
                field="category",
                intent=_list(c.allowed_categories),
                cart=_list(cats),
                match=all(x in c.allowed_categories for x in cats),
            )
        )
    if c.allowed_merchants is not None:
        rows.append(
            IntentCartRow(
                field="merchant",
                intent=_list(c.allowed_merchants),
                cart=cart.merchant_id,
                match=cart.merchant_id in c.allowed_merchants,
            )
        )
    for key, want in sorted(c.required_attributes.items()):
        got = [i.attributes.get(key) for i in cart.items]
        rows.append(
            IntentCartRow(
                field=f"attribute:{key}",
                intent=want,
                cart=", ".join(g if g is not None else "missing" for g in got) or "no items",
                match=bool(got) and all(g == want for g in got),
            )
        )
    if c.expires_at is not None:
        rows.append(
            IntentCartRow(
                field="expires_at",
                intent=c.expires_at,
                cart=cart.created_at,
                match=cart.created_at <= c.expires_at,
            )
        )
    return rows


def excerpt(content: str, start: int, end: int, limit: int = MAX_EXCERPT_CHARS) -> str:
    """The flagged range plus surrounding context, never longer than ``limit`` characters."""
    start = max(0, min(start, len(content)))
    end = max(start, min(end, len(content)))
    if end - start >= limit:
        return content[start : start + limit]
    pad = min(_CONTEXT_CHARS, (limit - (end - start)) // 2)
    return content[max(0, start - pad) : min(len(content), end + pad)]


def _excerpts(case: CaseFile, spans: list[Span]) -> list[FlaggedExcerpt]:
    steps = {s.step_id: s for s in case.trace}
    out: list[FlaggedExcerpt] = []
    seen: set[tuple[str, int, int]] = set()
    for sp in spans:
        step = steps.get(sp.step_id)
        key = (sp.step_id, sp.start, sp.end)
        if step is None or key in seen:
            continue
        seen.add(key)
        out.append(
            FlaggedExcerpt(
                step_id=sp.step_id,
                source=step.source,
                start=sp.start,
                end=sp.end,
                text=excerpt(step.content, sp.start, sp.end),
                rule_id=sp.rule_id,
                reason=sp.reason,
                method=sp.method,
            )
        )
    return out


# --- public API ----------------------------------------------------------------------------------


def build_packet(case: CaseFile, report: Report, generated_at: str | None = None) -> EvidencePacket:
    """Build the evidence packet for ``report``. ``generated_at`` defaults to the current UTC time."""
    stamp = generated_at or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return EvidencePacket(
        case_id=report.case_id,
        verdict=report.verdict,
        confidence=report.confidence,
        rule_id=report.rule_id,
        summary=_summary(report),
        findings=report.findings,
        secondary_findings=report.secondary_findings,
        intent_vs_cart=intent_vs_cart(case),
        flagged_excerpts=_excerpts(case, report.detection_spans),
        replay=report.replay,
        generated_at=stamp,
        tool_version=__version__,
    )


def to_json(packet: EvidencePacket) -> str:
    return packet.model_dump_json(indent=2)


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _finding_lines(findings: list[Finding]) -> list[str]:
    lines: list[str] = []
    for f in findings:
        method = f.method or "n/a"
        steps = ", ".join(f.step_ids) or "none"
        spans = ", ".join(f"{s.step_id}[{s.start}:{s.end}]" for s in f.spans) or "none"
        lines.append(
            f"- **{f.kind}**: {f.detail or 'no detail'} (method: {method}; steps: {steps}; spans: {spans})"
        )
    return lines


def to_markdown(packet: EvidencePacket) -> str:
    out: list[str] = [
        f"# Evidence packet: {packet.case_id}",
        "",
        f"> {packet.notice}",
        "",
        "## Verdict",
        "",
        f"- Verdict: {packet.verdict}",
        f"- Confidence: {packet.confidence}",
        f"- Rule: {packet.rule_id}",
        "",
        "## Summary",
        "",
        packet.summary,
        "",
        "## Findings",
        "",
    ]
    out += _finding_lines(packet.findings) or ["No primary findings."]
    if packet.secondary_findings:
        out += ["", "### Secondary findings", ""] + _finding_lines(packet.secondary_findings)
    out += ["", "## Intent vs cart", "", "| Field | Intent | Cart | Match |", "| --- | --- | --- | --- |"]
    for r in packet.intent_vs_cart:
        out.append(
            f"| {_cell(r.field)} | {_cell(r.intent)} | {_cell(r.cart)} | {'yes' if r.match else 'no'} |"
        )
    out += ["", "## Flagged excerpts", ""]
    if packet.flagged_excerpts:
        for e in packet.flagged_excerpts:
            label = f"{e.step_id} ({e.source}) [{e.start}:{e.end}]"
            if e.reason:
                label += f", {e.reason}"
            out += [f"- {label}", "", "  ```text", f"  {e.text.replace(chr(10), ' ')}", "  ```"]
    else:
        out.append("None.")
    out += ["", "## Replay", ""]
    r = packet.replay
    if r is None:
        out.append("Not run.")
    elif r.result == "unavailable":
        out.append(f"Unavailable: {r.reason or 'no reason recorded'}.")
    else:
        out.append(
            f"Result: {r.result}. Original product: {r.original_product_id}. "
            f"Replay product: {r.replay_product_id}. Spans removed: {r.removed_span_count}."
        )
    out += [
        "",
        "---",
        f"Generated at {packet.generated_at} by IntentTrace {packet.tool_version}.",
        "",
        packet.notice,
        "",
    ]
    return "\n".join(out)
