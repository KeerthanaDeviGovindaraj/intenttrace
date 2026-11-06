"""Influence score (design.md section 6.3).

``influence = 0.4 * lexical + 0.6 * llm_score``. If the LLM is unavailable, ``influence = lexical``
and an ``llm_unavailable`` finding is recorded.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

from pydantic import BaseModel, Field

from intenttrace.llm.base import LLMProvider, LLMUnavailable, call_validated
from intenttrace.llm.prompts import INFLUENCE_SYSTEM, InfluenceJudgment, influence_user
from intenttrace.models import CaseFile, Finding, Span

LEXICAL_WEIGHT = 0.4
LLM_WEIGHT = 0.6
MIN_WORD_LEN = 4

_WORD = re.compile(r"[a-z]+(?:'[a-z]+)?")
_STOPWORDS = frozenset(
    "this that with from your have will they them then than were what when which while would could "
    "should about into over only also been being their there these those just very more most some such "
    "item items product products".split()
)


class InfluenceResult(BaseModel):
    lexical: float
    llm_score: float | None = None
    influence: float
    evidence_step_ids: list[str] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)


def content_words(text: str) -> set[str]:
    """Lowercased words of length >= 4 with stopwords removed."""
    return {w for w in _WORD.findall(text.lower()) if len(w) >= MIN_WORD_LEN and w not in _STOPWORDS}


def overlap_share(span_text: str, reasoning_texts: Iterable[str]) -> float:
    """Share of the span's content words that appear in the reasoning texts."""
    words = content_words(span_text)
    if not words:
        return 0.0
    seen: set[str] = set()
    for t in reasoning_texts:
        seen |= content_words(t)
    return len(words & seen) / len(words)


def span_text(case: CaseFile, span: Span) -> str:
    for step in case.trace:
        if step.step_id == span.step_id:
            return step.content[span.start : span.end]
    return ""


def reasoning_steps(case: CaseFile) -> list[tuple[str, str]]:
    return [(s.step_id, s.content) for s in case.trace if s.kind in ("think", "decide")]


def lexical_score(case: CaseFile, spans: Sequence[Span]) -> float:
    """Maximum over spans of the overlap share with the agent's think and decide steps."""
    reasoning = [text for _, text in reasoning_steps(case)]
    return max((overlap_share(span_text(case, s), reasoning) for s in spans), default=0.0)


def combine(lexical: float, llm_score: float | None) -> float:
    if llm_score is None:
        return lexical
    return LEXICAL_WEIGHT * lexical + LLM_WEIGHT * llm_score


def compute_influence(case: CaseFile, spans: Sequence[Span], provider: LLMProvider | None) -> InfluenceResult:
    """Score how much the agent's reasoning relied on the flagged spans (0 when nothing is flagged)."""
    if not spans:
        return InfluenceResult(lexical=0.0, influence=0.0)

    lexical = lexical_score(case, spans)
    if provider is None:
        return InfluenceResult(lexical=lexical, influence=lexical)

    reasoning = reasoning_steps(case)
    user = influence_user(case.intent.natural_language, [span_text(case, s) for s in spans], reasoning)
    try:
        judgment = call_validated(provider, INFLUENCE_SYSTEM, user, InfluenceJudgment)
    except LLMUnavailable as exc:
        finding = Finding(
            kind="llm_unavailable",
            detail=f"Influence judgment unavailable ({exc}); using lexical score only.",
            field="influence",
            method="deterministic",
        )
        return InfluenceResult(lexical=lexical, influence=lexical, findings=[finding])
    return InfluenceResult(
        lexical=lexical,
        llm_score=judgment.score,
        influence=combine(lexical, judgment.score),
        evidence_step_ids=judgment.evidence_step_ids,
    )
