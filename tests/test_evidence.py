"""Evidence packet (Requirements 7.3-7.4)."""

import json

import pytest

from intenttrace.evidence import (
    MAX_EXCERPT_CHARS,
    NOTICE,
    EvidencePacket,
    build_packet,
    excerpt,
    to_json,
    to_markdown,
)
from intenttrace.llm.fake import FakeProvider
from intenttrace.pipeline import investigate
from intenttrace.sim.generate import build_cases


@pytest.fixture(scope="module")
def generated():
    return build_cases(40, 5)


def test_notice_text():
    assert NOTICE == (
        "This report describes technical findings from synthetic test data. "
        "It is not legal advice and does not determine liability."
    )


def test_summary_and_notice_for_every_verdict(generated):
    seen = set()
    for g in generated:
        report = investigate(g.case, provider=FakeProvider())
        packet = build_packet(g.case, report)
        seen.add(packet.verdict)
        assert packet.summary
        assert packet.summary.count(". ") + 1 <= 4 + 1
        assert packet.notice == NOTICE
        md = to_markdown(packet)
        assert NOTICE in md
        assert packet.verdict in md and packet.summary in md
        assert "| Field | Intent | Cart | Match |" in md
        data = json.loads(to_json(packet))
        assert data["notice"] == NOTICE
        assert EvidencePacket.model_validate(data) == packet
        for e in packet.flagged_excerpts:
            assert len(e.text) <= MAX_EXCERPT_CHARS
    assert {"INTEGRITY_FAILURE", "OUT_OF_SCOPE", "MERCHANT_MISREPRESENTATION", "LEGITIMATE"} <= seen


def test_summaries_differ_by_verdict(generated):
    by_verdict = {}
    for g in generated:
        p = build_packet(g.case, investigate(g.case, provider=FakeProvider()))
        by_verdict.setdefault(p.verdict, p.summary)
    assert len(set(by_verdict.values())) == len(by_verdict)


def test_manipulated_packet_has_excerpts(generated):
    for g in generated:
        report = investigate(g.case, provider=FakeProvider())
        if report.verdict == "MANIPULATED":
            packet = build_packet(g.case, report)
            assert packet.flagged_excerpts
            assert packet.replay is not None
            return
    pytest.fail("no MANIPULATED case generated")


def test_excerpt_length_cap_and_context():
    content = "a" * 500 + "BAD" + "b" * 500
    short = excerpt(content, 500, 503)
    assert "BAD" in short and len(short) <= MAX_EXCERPT_CHARS and len(short) > 3
    long_span = excerpt(content, 0, 1000)
    assert len(long_span) == MAX_EXCERPT_CHARS
    assert excerpt("hi", 0, 2) == "hi"


def test_intent_vs_cart_matches_for_valid_case(signed_case):
    case, _ = signed_case
    packet = build_packet(case, investigate(case), generated_at="2025-01-01T00:00:00Z")
    assert packet.generated_at == "2025-01-01T00:00:00Z"
    assert packet.intent_vs_cart
    assert all(r.match for r in packet.intent_vs_cart)
