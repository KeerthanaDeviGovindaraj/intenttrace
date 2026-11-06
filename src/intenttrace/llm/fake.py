"""Deterministic fake provider (design.md section 10). Default in tests and CI.

Numbers produced with this provider test the pipeline, not model accuracy.
"""

from __future__ import annotations

import json
from typing import Literal

from intenttrace.llm.base import LLMError, T, Usage
from intenttrace.llm.prompts import ClassifiedSpan, ClassifyResult, InfluenceJudgment

PERSUASION_PHRASES = ("best choice", "trusted by", "you'll regret", "everyone picks")
_SENTENCE_END = ".!?"


def _sentence_bounds(text: str, index: int) -> tuple[int, int]:
    start = index
    while start > 0 and text[start - 1] not in _SENTENCE_END:
        start -= 1
    while start < len(text) and text[start].isspace():
        start += 1
    end = index
    while end < len(text) and text[end] not in _SENTENCE_END:
        end += 1
    return start, min(end + 1, len(text))


class FakeProvider:
    """``fail`` simulates outages: ``"always"`` raises every call, ``"once"`` fails the first call."""

    name = "fake"

    def __init__(self, fail: Literal["always", "once"] | None = None, model: str = "fake-deterministic"):
        self.model = model
        self.usage = Usage()
        self._fail = fail
        self._failed_once = False

    def complete_json(self, system: str, user: str, schema: type[T]) -> T:
        if self._fail == "always" or (self._fail == "once" and not self._failed_once):
            self._failed_once = True
            self.usage.record(len(system + user) // 4, 0)
            raise LLMError("fake provider configured to fail")
        try:
            payload = json.loads(user)
        except json.JSONDecodeError as exc:
            raise LLMError("fake provider needs a JSON user message") from exc

        if schema is ClassifyResult:
            result: object = self._classify(payload["text"])
        elif schema is InfluenceJudgment:
            result = self._judge(payload)
        else:
            raise LLMError(f"fake provider does not support schema {schema.__name__}")
        out = schema.model_validate(result.model_dump())
        self.usage.record(len(system + user) // 4, len(out.model_dump_json()) // 4)
        return out

    @staticmethod
    def _classify(text: str) -> ClassifyResult:
        lowered = text.lower()
        spans: list[ClassifiedSpan] = []
        for phrase in PERSUASION_PHRASES:
            idx = lowered.find(phrase)
            if idx >= 0:
                start, end = _sentence_bounds(text, idx)
                if not any(s.start == start and s.end == end for s in spans):
                    spans.append(ClassifiedSpan(start=start, end=end, reason=f"persuasion: {phrase}"))
        spans.sort(key=lambda s: s.start)
        return ClassifyResult(suspicious=bool(spans), spans=spans)

    @staticmethod
    def _judge(payload: dict) -> InfluenceJudgment:
        # Imported here to keep llm/ free of an import cycle with forensics/.
        from intenttrace.forensics.influence import overlap_share

        reasoning = [(r["step_id"], r["content"]) for r in payload["reasoning"]]
        texts = [t for _, t in reasoning]
        score = max((overlap_share(f, texts) for f in payload["flagged_spans"]), default=0.0)
        evidence = [
            sid
            for sid, content in reasoning
            if any(overlap_share(f, [content]) > 0 for f in payload["flagged_spans"])
        ]
        return InfluenceJudgment(relied_on_flagged=score >= 0.5, score=score, evidence_step_ids=evidence)
