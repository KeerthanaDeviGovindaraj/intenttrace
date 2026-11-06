"""Verdict rules V1-V10 (plus V5b, V6a) (design.md section 8). Ordered, first match wins, never raises."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from intenttrace.checks.integrity import IntegrityResult
from intenttrace.checks.merchant import MerchantResult
from intenttrace.checks.scope import ScopeResult
from intenttrace.config import DEFAULT_THRESHOLDS, Thresholds
from intenttrace.forensics.detect import DetectionResult
from intenttrace.forensics.deviation import DeviationResult
from intenttrace.forensics.influence import InfluenceResult
from intenttrace.forensics.replay import ReplayResult
from intenttrace.models import CaseFile, Finding, Span

VerdictLabel = Literal[
    "LEGITIMATE",
    "MANIPULATED",
    "OUT_OF_SCOPE",
    "MERCHANT_MISREPRESENTATION",
    "INTEGRITY_FAILURE",
    "INCONCLUSIVE",
]
Confidence = Literal["high", "medium", "low"]


class Verdict(BaseModel):
    verdict: VerdictLabel
    confidence: Confidence
    rule_id: str
    findings: list[Finding] = Field(default_factory=list)  # findings that decided the verdict
    secondary_findings: list[Finding] = Field(default_factory=list)  # everything else, always listed


def _secondary(
    primary: list[Finding],
    integrity: IntegrityResult | None,
    scope: ScopeResult | None,
    merchant: MerchantResult | None,
    detection: DetectionResult | None,
    influence: InfluenceResult | None,
    extra: list[Finding],
) -> list[Finding]:
    """Every finding from every stage that ran, minus those already reported as primary."""
    pool: list[Finding] = []
    if integrity:
        pool += integrity.failures
    if scope:
        pool += scope.violations
    if merchant:
        pool += merchant.material + merchant.non_material
    if detection:
        pool += detection.findings
    if influence:
        pool += influence.findings
    pool += extra
    return [f for f in pool if not any(f is p for p in primary)]


def _span_on_purchased_product(case: CaseFile | None, spans: list[Span], product_id: str | None) -> bool:
    """True when a flagged span sits in a merchant listing or review step of the purchased product."""
    if case is None or product_id is None:
        return False
    steps = {s.step_id: s for s in case.trace}
    for span in spans:
        step = steps.get(span.step_id)
        if step and step.source in ("merchant", "review") and step.product_id == product_id:
            return True
    return False


def _unexplained(detail: str, deviation: DeviationResult | None) -> Finding:
    return Finding(
        kind="unexplained_deviation",
        detail=detail,
        expected=deviation.top_ranked_product_id if deviation else None,
        actual=deviation.chosen_product_id if deviation else None,
        method="deterministic",
    )


def decide(
    integrity: IntegrityResult | None = None,
    scope: ScopeResult | None = None,
    merchant: MerchantResult | None = None,
    detection: DetectionResult | None = None,
    deviation: DeviationResult | None = None,
    influence: InfluenceResult | None = None,
    replay: ReplayResult | None = None,
    thresholds: Thresholds = DEFAULT_THRESHOLDS,
    case: CaseFile | None = None,
) -> Verdict:
    """Apply V1-V10 in order. Stages that did not run are passed as None."""
    flagged = bool(detection and detection.spans)
    deviated = bool(deviation and deviation.deviation)
    score = influence.influence if influence else 0.0
    replay_outcome = replay.result if replay else "unavailable"

    extra: list[Finding] = []
    if flagged and detection:
        extra.append(
            Finding(
                kind="flagged_content_present",
                detail=f"{len(detection.spans)} untrusted span(s) flagged in the trace.",
                step_ids=detection.flagged_step_ids,
                spans=list(detection.spans),
                method="deterministic",
            )
        )
    if deviated and deviation:
        extra.append(
            Finding(
                kind="deviation",
                detail="Chosen product differs from the top-ranked eligible product.",
                expected=deviation.top_ranked_product_id,
                actual=deviation.chosen_product_id,
                method="deterministic",
            )
        )

    primary: list[Finding] = []
    if integrity and integrity.failures:
        label, conf, rule, primary = "INTEGRITY_FAILURE", "high", "V1", list(integrity.failures)
    elif scope and scope.violations:
        label, conf, rule, primary = "OUT_OF_SCOPE", "high", "V2", list(scope.violations)
    elif merchant and merchant.material:
        label, conf, rule, primary = "MERCHANT_MISREPRESENTATION", "high", "V3", list(merchant.material)
    elif replay_outcome == "changed":
        label, conf, rule = "MANIPULATED", "high", "V4"
    elif replay_outcome == "unchanged" and not deviated:
        label, conf, rule = "LEGITIMATE", "high", "V5"
    elif replay_outcome == "unchanged" and deviated:
        # Replay only clears what it tested: the deviation is not explained by the flagged content.
        label, conf, rule = "INCONCLUSIVE", "low", "V5b"
        primary = [
            _unexplained(
                "deviation not explained by flagged content; possible undetected manipulation.", deviation
            )
        ]
    elif (
        deviated
        and detection
        and _span_on_purchased_product(
            case, detection.spans, deviation.chosen_product_id if deviation else None
        )
    ):
        label, conf, rule = "MANIPULATED", "medium", "V6a"
        primary = [
            Finding(
                kind="attribution_purchased_product",
                detail="suspicious content attached to purchased product.",
                step_ids=detection.flagged_step_ids,
                spans=list(detection.spans),
                method="deterministic",
            )
        ]
    elif flagged and deviated and score >= thresholds.influence_manipulated:
        label, conf, rule = "MANIPULATED", "medium", "V6"
    elif not flagged and not deviated:
        label, conf, rule = "LEGITIMATE", "high", "V7"
    elif flagged and not deviated and score < thresholds.influence_legitimate:
        label, conf, rule = "LEGITIMATE", "medium", "V8"
    elif not flagged and deviated:
        label, conf, rule = "INCONCLUSIVE", "low", "V9"
        primary = [
            _unexplained("Choice differs from the best match but no manipulation was found.", deviation)
        ]
    else:
        label, conf, rule = "INCONCLUSIVE", "low", "V10"

    # Findings used as primary evidence are not repeated in the secondary list.
    extra = [f for f in extra if not any(f is p for p in primary)]
    return Verdict(
        verdict=label,  # type: ignore[arg-type]
        confidence=conf,  # type: ignore[arg-type]
        rule_id=rule,
        findings=primary,
        secondary_findings=_secondary(primary, integrity, scope, merchant, detection, influence, extra),
    )
