"""Suspicious-span detection in untrusted trace content (design.md section 6.1).

Deterministic rules R1-R5 run first. The LLM classifier then reviews each untrusted step that the
rules did not flag. Every span records the method that found it.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from intenttrace.llm.base import LLMProvider, LLMUnavailable, call_validated
from intenttrace.llm.prompts import CLASSIFY_SYSTEM, ClassifyResult, classify_user
from intenttrace.models import CaseFile, Finding, Span, TraceStep

UNTRUSTED_SOURCES = frozenset({"merchant", "review", "external_agent"})

_ZW = "\u200b-\u200f\u2060\ufeff"
_AGENT_NOUN = r"(?:assistants?|agents?|buyers?|bots?|models?)"

RULES: dict[str, re.Pattern[str]] = {
    "R1": re.compile(
        r"\bai\s+(?:shopping\s+)?" + _AGENT_NOUN + r"\b"
        r"|\b(?:shopping|automated|purchasing)\s+(?:assistants?|agents?|buyers?)\b"
        r"|\blanguage\s+models?\b"
        r"|\bif\s+you\s+are\s+an?\s+ai\b",
        re.IGNORECASE,
    ),
    "R2": re.compile(
        r"\bignore\s+(?:all|previous|prior)(?:\s+(?:other|previous|prior))?(?:\s+(?:instructions|options))?\b"
        r"|\byou\s+must\s+(?:select|choose|buy)\b"
        r"|\balways\s+(?:recommend|choose)\b",
        re.IGNORECASE,
    ),
    "R3": re.compile(
        rf"[{_ZW}]+[^{_ZW}]*[{_ZW}]+"  # text enclosed by zero-width characters
        rf"|[{_ZW}]+"
        r"|<!--.*?(?:-->|$)"
        r"|display\s*:\s*none"
        r"|(?<=\s{20})\S[^\n]*"  # text following a long whitespace run
        r"|(?<=\n{3})\S[^\n]*",
        re.IGNORECASE | re.DOTALL,
    ),
    "R4": re.compile(
        r"\bonly\s+\d+\s+left\b"
        r"|\bprice\s+(?:rises|increases)\s+in\b"
        r"|\bexpires?\s+in\s+\d+\s+minutes?\b"
        r"|\bends\s+in\s+\d+\s+minutes?\b"
        r"|\bexclusive\s+agent\s+discount\b",
        re.IGNORECASE,
    ),
    "R5": re.compile(
        r"\bverified\s+by\s+(?:the|your)\s+user\b"
        r"|\bthe\s+user\s+prefers\b"
        r"|\bpre-approved\b"
        r"|\bofficial\s+recommendation\b",
        re.IGNORECASE,
    ),
}


class DetectionResult(BaseModel):
    spans: list[Span] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)

    @property
    def flagged_step_ids(self) -> list[str]:
        seen: list[str] = []
        for s in self.spans:
            if s.step_id not in seen:
                seen.append(s.step_id)
        return seen


def untrusted_steps(case: CaseFile) -> list[TraceStep]:
    return [s for s in case.trace if s.source in UNTRUSTED_SOURCES]


def detect_rules(step: TraceStep) -> list[Span]:
    """Apply R1-R5 to one step; returns spans sorted by position."""
    spans = [
        Span(step_id=step.step_id, start=m.start(), end=m.end(), rule_id=rule_id, method="rule")
        for rule_id, pattern in RULES.items()
        for m in pattern.finditer(step.content)
        if m.end() > m.start()
    ]
    return sorted(spans, key=lambda s: (s.start, s.end, s.rule_id or ""))


def _classify_step(step: TraceStep, provider: LLMProvider) -> list[Span]:
    length = len(step.content)

    def check(result: ClassifyResult) -> None:
        for sp in result.spans:
            if not (0 <= sp.start < sp.end <= length):
                raise ValueError(f"span offsets out of range: {sp.start}-{sp.end} for length {length}")

    result = call_validated(provider, CLASSIFY_SYSTEM, classify_user(step.content), ClassifyResult, check)
    if not result.suspicious:
        return []
    return [
        Span(step_id=step.step_id, start=sp.start, end=sp.end, rule_id="LLM", reason=sp.reason, method="llm")
        for sp in result.spans
    ]


def detect(case: CaseFile, provider: LLMProvider | None = None) -> DetectionResult:
    """Find suspicious spans in untrusted steps; ``provider=None`` runs the rules only."""
    spans: list[Span] = []
    findings: list[Finding] = []
    llm_failed_steps: list[str] = []

    for step in untrusted_steps(case):
        rule_spans = detect_rules(step)
        step_spans = rule_spans
        if not rule_spans and provider is not None:
            try:
                step_spans = _classify_step(step, provider)
            except LLMUnavailable:
                llm_failed_steps.append(step.step_id)
        if step_spans:
            spans.extend(step_spans)
            findings.append(
                Finding(
                    kind="flagged_content",
                    detail=f"Suspicious content in {step.source} step {step.step_id}.",
                    step_ids=[step.step_id],
                    spans=step_spans,
                    method=step_spans[0].method,
                )
            )

    if llm_failed_steps:
        findings.append(
            Finding(
                kind="llm_unavailable",
                detail="LLM classifier unavailable; only deterministic rules were applied to these steps.",
                field="classify",
                step_ids=llm_failed_steps,
                method="deterministic",
            )
        )
    return DetectionResult(spans=spans, findings=findings)
