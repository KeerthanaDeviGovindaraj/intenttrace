"""Investigation pipeline (design.md overview and sections 3-8).

Stages run in order: integrity, scope, merchant, forensics (detect, deviation, influence), replay,
then ``verdict.decide``. Deterministic stages V1-V3 end the investigation early; later stages are
recorded as skipped. Missing optional data never raises: the stage notes say what was skipped.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from intenttrace.checks.integrity import IntegrityResult, check_integrity
from intenttrace.checks.merchant import MerchantResult, check_merchant
from intenttrace.checks.scope import ScopeResult, check_scope
from intenttrace.config import DEFAULT_THRESHOLDS, Thresholds
from intenttrace.forensics.detect import DetectionResult, detect
from intenttrace.forensics.deviation import DeviationResult, check_deviation
from intenttrace.forensics.influence import InfluenceResult, compute_influence
from intenttrace.forensics.replay import ReplayResult, original_choice
from intenttrace.forensics.replay import replay as run_replay
from intenttrace.llm.base import LLMProvider
from intenttrace.models import CaseFile, Finding, Span
from intenttrace.verdict import Confidence, VerdictLabel, decide

STAGES = ("integrity", "scope", "merchant", "detect", "deviation", "influence", "replay")


class StageNote(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: str
    status: Literal["ran", "skipped"]
    reason: str | None = None


class Report(BaseModel):
    """Everything evidence.py needs to render a packet."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    verdict: VerdictLabel
    confidence: Confidence
    rule_id: str
    findings: list[Finding] = Field(default_factory=list)
    secondary_findings: list[Finding] = Field(default_factory=list)
    detection_spans: list[Span] = Field(default_factory=list)
    deviation: DeviationResult | None = None
    influence: InfluenceResult | None = None
    replay: ReplayResult | None = None
    integrity: IntegrityResult | None = None
    scope: ScopeResult | None = None
    merchant: MerchantResult | None = None
    stages: list[StageNote] = Field(default_factory=list)
    skipped_notes: list[str] = Field(default_factory=list)
    provider: str | None = None  # LLM provider name, None when no provider was used
    model: str | None = None
    early_exit: bool = False


def investigate(
    case: CaseFile,
    replay: bool = True,
    provider: LLMProvider | None = None,
    thresholds: Thresholds = DEFAULT_THRESHOLDS,
) -> Report:
    """Run all stages on ``case`` and return a Report. ``provider=None`` skips LLM assistance."""
    notes: list[StageNote] = []

    def ran(stage: str) -> None:
        notes.append(StageNote(stage=stage, status="ran"))

    def skipped(stage: str, reason: str) -> None:
        notes.append(StageNote(stage=stage, status="skipped", reason=reason))

    def finish(
        integrity: IntegrityResult | None = None,
        scope: ScopeResult | None = None,
        merchant: MerchantResult | None = None,
        detection: DetectionResult | None = None,
        deviation: DeviationResult | None = None,
        influence: InfluenceResult | None = None,
        replay_result: ReplayResult | None = None,
        early: bool = False,
    ) -> Report:
        v = decide(
            integrity, scope, merchant, detection, deviation, influence, replay_result, thresholds, case
        )
        done = {n.stage for n in notes}
        for stage in STAGES:
            if stage not in done:
                skipped(stage, "not reached")
        order = {s: i for i, s in enumerate(STAGES)}
        notes.sort(key=lambda n: order[n.stage])
        skip_lines = [f"{n.stage}: {n.reason}" for n in notes if n.status == "skipped" and n.reason]
        if merchant:
            skip_lines += [f"merchant: {s}" for s in merchant.skipped]
        return Report(
            case_id=case.case_id,
            verdict=v.verdict,
            confidence=v.confidence,
            rule_id=v.rule_id,
            findings=v.findings,
            secondary_findings=v.secondary_findings,
            detection_spans=list(detection.spans) if detection else [],
            deviation=deviation,
            influence=influence,
            replay=replay_result,
            integrity=integrity,
            scope=scope,
            merchant=merchant,
            stages=notes,
            skipped_notes=skip_lines,
            provider=provider.name if provider else None,
            model=provider.model if provider else None,
            early_exit=early,
        )

    integrity = check_integrity(case)
    ran("integrity")
    if integrity.failures:
        skipped_reason = "early exit: integrity failure (V1)"
        return _early(finish, notes, integrity=integrity, reason=skipped_reason)

    scope = check_scope(case)
    ran("scope")
    if scope.violations:
        return _early(
            finish, notes, integrity=integrity, scope=scope, reason="early exit: scope violation (V2)"
        )

    merchant = check_merchant(case)
    ran("merchant")
    if merchant.material:
        return _early(
            finish,
            notes,
            integrity=integrity,
            scope=scope,
            merchant=merchant,
            reason="early exit: material merchant difference (V3)",
        )

    detection = detect(case, provider)
    ran("detect")

    chosen = original_choice(case)
    if case.listings_at_purchase:
        deviation = check_deviation(
            case.intent.natural_language, case.intent.constraints, case.listings_at_purchase, chosen
        )
        ran("deviation")
    else:
        deviation = None
        skipped("deviation", "no listings_at_purchase")

    influence = compute_influence(case, detection.spans, provider)
    ran("influence")

    if not replay:
        replay_result = run_replay(case, detection.spans, enabled=False)
        skipped("replay", "replay disabled")
    else:
        replay_result = run_replay(case, detection.spans, enabled=True)
        if replay_result.result == "unavailable":
            skipped("replay", replay_result.reason or "unavailable")
        else:
            ran("replay")

    return finish(integrity, scope, merchant, detection, deviation, influence, replay_result)


def _early(finish, notes: list[StageNote], reason: str, **stages) -> Report:
    """Mark every stage not yet run as skipped with the early-exit reason, then build the report."""
    done = {n.stage for n in notes}
    for stage in STAGES:
        if stage not in done:
            notes.append(StageNote(stage=stage, status="skipped", reason=reason))
    return finish(early=True, **stages)
