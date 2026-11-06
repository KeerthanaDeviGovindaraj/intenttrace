"""Pipeline orchestration (Requirements 6.1-6.4, 7.1)."""

import pytest

from intenttrace.llm.fake import FakeProvider
from intenttrace.pipeline import STAGES, Report, investigate
from intenttrace.sim.generate import build_cases


@pytest.fixture(scope="module")
def generated():
    return build_cases(40, 5)


def _by_label(generated, label):
    return [g for g in generated if g.label["label"] == label]


def test_report_roundtrips_json(generated):
    report = investigate(generated[0].case, provider=FakeProvider())
    assert Report.model_validate_json(report.model_dump_json()) == report
    assert [n.stage for n in report.stages] == list(STAGES)


@pytest.mark.parametrize(
    ("label", "rule"),
    [("INTEGRITY_FAILURE", "V1"), ("OUT_OF_SCOPE", "V2"), ("MERCHANT_MISREPRESENTATION", "V3")],
)
def test_deterministic_buckets_exit_early(generated, label, rule):
    cases = _by_label(generated, label)
    assert cases
    for g in cases:
        report = investigate(g.case, provider=FakeProvider())
        assert (report.verdict, report.rule_id, report.confidence) == (label, rule, "high")
        assert report.early_exit
        assert report.findings
        skipped = {n.stage for n in report.stages if n.status == "skipped"}
        assert {"detect", "influence", "replay"} <= skipped
        assert report.deviation is None


def test_forensic_buckets_match_labels_with_fake_provider(generated):
    for label in ("LEGITIMATE", "MANIPULATED"):
        cases = _by_label(generated, label)
        assert cases
        for g in cases:
            report = investigate(g.case, provider=FakeProvider())
            # Cases without agent_config cannot be replayed; the heuristic rules may be inconclusive.
            if g.case.agent_config is not None:
                if g.label["attack_type"] == "subtle_persuasion" and not report.detection_spans:
                    # Known limitation: the fake classifier cannot flag subtle persuasion, so replay
                    # removes nothing and reports "unchanged".
                    continue
                assert report.verdict == label, g.case.case_id
                assert report.rule_id in ("V4", "V5", "V7")
            elif label == "LEGITIMATE":
                # Without replay the pipeline must never falsely accuse a legitimate purchase.
                assert report.verdict != "MANIPULATED", g.case.case_id


def test_no_replay_skips_replay_stage(generated):
    g = next(x for x in _by_label(generated, "MANIPULATED") if x.case.agent_config is not None)
    report = investigate(g.case, replay=False, provider=FakeProvider())
    assert report.replay is not None and report.replay.result == "unavailable"
    assert report.rule_id not in ("V4", "V5")
    assert any(n.stage == "replay" and n.status == "skipped" for n in report.stages)
    assert any(s.startswith("replay:") for s in report.skipped_notes)


def test_degrades_without_optional_data(generated):
    g = next(x for x in _by_label(generated, "LEGITIMATE"))
    case = g.case.model_copy(update={"agent_config": None, "listing_after": None, "delivered": None})
    report = investigate(case, provider=None)
    assert report.verdict in ("LEGITIMATE", "INCONCLUSIVE")
    assert report.provider is None
    assert any("listing_after" in s for s in report.skipped_notes)
    assert any(s.startswith("replay:") for s in report.skipped_notes)


def test_no_listings_skips_deviation(generated):
    g = _by_label(generated, "LEGITIMATE")[0]
    case = g.case.model_copy(update={"listings_at_purchase": [], "listing_after": None, "delivered": None})
    report = investigate(case, provider=None)
    assert report.deviation is None
    assert any(n.stage == "deviation" and n.status == "skipped" for n in report.stages)


def test_llm_outage_still_returns_report(generated):
    g = _by_label(generated, "MANIPULATED")[0]
    report = investigate(g.case, provider=FakeProvider(fail="always"))
    assert report.verdict in ("MANIPULATED", "LEGITIMATE", "INCONCLUSIVE")
    assert report.provider == "fake"
