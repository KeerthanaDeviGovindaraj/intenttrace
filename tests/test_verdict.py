"""Tests for verdict.py (rules V1-V10, V5b, V6a)."""

from __future__ import annotations

from intenttrace.checks.integrity import IntegrityResult
from intenttrace.checks.merchant import MerchantResult
from intenttrace.checks.scope import ScopeResult
from intenttrace.config import Thresholds
from intenttrace.forensics.detect import DetectionResult
from intenttrace.forensics.deviation import DeviationResult
from intenttrace.forensics.influence import InfluenceResult
from intenttrace.forensics.replay import ReplayResult
from intenttrace.models import CaseFile, Finding, Span, TraceStep
from intenttrace.verdict import decide

F = Finding(kind="x", detail="d")
SPANS = DetectionResult(spans=[Span(step_id="s02", start=0, end=5, rule_id="R1", method="rule")])
NONE = DetectionResult()


def _dev(flag: bool) -> DeviationResult:
    chosen = "b" if flag else "a"
    return DeviationResult(top_ranked_product_id="a", top=[], chosen_product_id=chosen, deviation=flag)


def _inf(x: float) -> InfluenceResult:
    return InfluenceResult(lexical=x, influence=x)


def _rep(outcome: str) -> ReplayResult:
    return ReplayResult(result=outcome)  # type: ignore[arg-type]


def _check(v, verdict: str, rule: str, conf: str) -> None:
    assert (v.verdict, v.rule_id, v.confidence) == (verdict, rule, conf)


def test_v1_integrity_failure() -> None:
    integ = IntegrityResult(ok=False, failures=[F])
    scope = ScopeResult(ok=False, violations=[F])
    merch = MerchantResult(ok=False, material=[F])
    v = decide(integ, scope, merch, replay=_rep("changed"))  # V1 outranks everything
    _check(v, "INTEGRITY_FAILURE", "V1", "high")
    assert v.findings == [F]


def test_v2_out_of_scope() -> None:
    scope = ScopeResult(ok=False, violations=[F])
    merch = MerchantResult(ok=False, material=[F])
    _check(decide(None, scope, merch, replay=_rep("changed")), "OUT_OF_SCOPE", "V2", "high")


def test_v3_merchant_misrepresentation() -> None:
    merch = MerchantResult(ok=False, material=[F])
    _check(decide(None, None, merch, replay=_rep("changed")), "MERCHANT_MISREPRESENTATION", "V3", "high")


def test_v4_replay_changed() -> None:
    v = decide(detection=SPANS, deviation=_dev(False), replay=_rep("changed"))
    _check(v, "MANIPULATED", "V4", "high")


def test_v5_replay_unchanged_no_deviation() -> None:
    rep = ReplayResult(result="unchanged", removed_span_count=1)
    v = decide(detection=SPANS, deviation=_dev(False), influence=_inf(0.9), replay=rep)
    _check(v, "LEGITIMATE", "V5", "high")


def test_v5b_replay_unchanged_with_deviation_is_inconclusive() -> None:
    for removed in (0, 1):
        rep = ReplayResult(result="unchanged", removed_span_count=removed)
        v = decide(
            detection=SPANS if removed else NONE, deviation=_dev(True), influence=_inf(0.9), replay=rep
        )
        _check(v, "INCONCLUSIVE", "V5b", "low")
        assert "possible undetected manipulation" in v.findings[0].detail


def _case_with_flagged_step(product_id: str, source: str = "merchant") -> CaseFile:
    step = TraceStep(
        step_id="s02", kind="observe", source=source, content="x", product_id=product_id, timestamp="t"
    )  # type: ignore[arg-type]
    return CaseFile.model_construct(trace=[step])


def test_v6a_flagged_span_on_purchased_product() -> None:
    for source in ("merchant", "review"):
        v = decide(
            detection=SPANS,
            deviation=_dev(True),
            influence=_inf(0.0),
            replay=_rep("unavailable"),
            case=_case_with_flagged_step("b", source),
        )
        _check(v, "MANIPULATED", "V6a", "medium")
        assert v.findings[0].detail == "suspicious content attached to purchased product."


def test_v6a_not_applied_when_span_is_on_another_product() -> None:
    v = decide(
        detection=SPANS,
        deviation=_dev(True),
        influence=_inf(0.0),
        replay=_rep("unavailable"),
        case=_case_with_flagged_step("c"),
    )
    _check(v, "INCONCLUSIVE", "V10", "low")


def test_v6a_comes_after_v5b() -> None:
    v = decide(
        detection=SPANS,
        deviation=_dev(True),
        replay=ReplayResult(result="unchanged", removed_span_count=1),
        case=_case_with_flagged_step("b"),
    )
    _check(v, "INCONCLUSIVE", "V5b", "low")


def test_v6_flagged_deviation_high_influence() -> None:
    v = decide(detection=SPANS, deviation=_dev(True), influence=_inf(0.6), replay=_rep("unavailable"))
    _check(v, "MANIPULATED", "V6", "medium")


def test_v7_nothing_flagged_no_deviation() -> None:
    _check(decide(detection=NONE, deviation=_dev(False)), "LEGITIMATE", "V7", "high")


def test_v8_flagged_no_deviation_low_influence() -> None:
    v = decide(detection=SPANS, deviation=_dev(False), influence=_inf(0.29))
    _check(v, "LEGITIMATE", "V8", "medium")


def test_v9_unexplained_deviation() -> None:
    v = decide(detection=NONE, deviation=_dev(True))
    _check(v, "INCONCLUSIVE", "V9", "low")
    assert v.findings[0].kind == "unexplained_deviation"


def test_v10_inconclusive() -> None:
    v = decide(detection=SPANS, deviation=_dev(True), influence=_inf(0.59))
    _check(v, "INCONCLUSIVE", "V10", "low")
    v = decide(detection=SPANS, deviation=_dev(False), influence=_inf(0.3))
    _check(v, "INCONCLUSIVE", "V10", "low")


def test_thresholds_configurable() -> None:
    t = Thresholds(influence_manipulated=0.9)
    v = decide(detection=SPANS, deviation=_dev(True), influence=_inf(0.7), thresholds=t)
    assert v.rule_id == "V10"


def test_secondary_findings_always_listed() -> None:
    v = decide(detection=SPANS, deviation=_dev(False), influence=_inf(0.1))
    kinds = [f.kind for f in v.secondary_findings]
    assert "flagged_content_present" in kinds
    merch = MerchantResult(ok=True, non_material=[Finding(kind="title_changed")])
    v = decide(None, None, merch, detection=NONE, deviation=_dev(False))
    assert [f.kind for f in v.secondary_findings] == ["title_changed"]
