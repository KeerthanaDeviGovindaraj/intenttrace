"""Tests for forensics/replay.py."""

from __future__ import annotations

import pytest

from intenttrace.forensics.detect import detect
from intenttrace.forensics.replay import build_observations, replay
from intenttrace.llm.fake import FakeProvider
from intenttrace.models import AgentConfig, Span
from intenttrace.sim.agents import detect_attacks
from intenttrace.sim.generate import GeneratedCase, build_cases


@pytest.fixture(scope="module")
def generated() -> list[GeneratedCase]:
    return build_cases(40, 1)


def _spans(g: GeneratedCase) -> list[Span]:
    return detect(g.case, FakeProvider()).spans


def test_replay_changed_for_manipulated_cases(generated: list[GeneratedCase]) -> None:
    checked = 0
    for g in generated:
        if g.label["label"] != "MANIPULATED" or g.case.agent_config is None:
            continue
        spans = _spans(g)
        if not spans:
            continue
        # Detector spans can cover only part of an attack (e.g. "Flash deal" is not matched by any
        # rule), so only assert when removal actually neutralized the attack text.
        if detect_attacks(build_observations(g.case, spans)):
            continue
        result = replay(g.case, spans)
        assert result.result == "changed", g.case.case_id
        assert result.original_product_id != result.replay_product_id
        checked += 1
    assert checked > 0


def test_replay_unchanged_when_attack_did_not_fool_agent(generated: list[GeneratedCase]) -> None:
    checked = 0
    for g in generated:
        if g.label["cause"] not in ("attack_present_choice_unchanged", "no_attack"):
            continue
        if g.case.agent_config is None:
            continue
        assert replay(g.case, _spans(g)).result == "unchanged", g.case.case_id
        checked += 1
    assert checked > 0


def test_replay_unavailable_without_config_or_when_disabled(generated: list[GeneratedCase]) -> None:
    no_config = next(g for g in generated if g.case.agent_config is None)
    assert replay(no_config.case, []).result == "unavailable"
    with_config = next(g for g in generated if g.case.agent_config is not None)
    disabled = replay(with_config.case, [], enabled=False)
    assert disabled.result == "unavailable"
    assert disabled.reason == "replay disabled"


def test_replay_unavailable_for_llm_agent(generated: list[GeneratedCase]) -> None:
    g = next(g for g in generated if g.case.agent_config is not None)
    llm = g.case.model_copy(update={"agent_config": AgentConfig(agent_type="llm", seed=1, model="m")})
    result = replay(llm, [])
    assert result.result == "unavailable"
    assert "not replayable" in (result.reason or "")


def test_build_observations_removes_flagged_text(generated: list[GeneratedCase]) -> None:
    g = next(g for g in generated if g.label["cause"] == "attack_changed_choice" and _spans(g))
    spans = _spans(g)
    obs = build_observations(g.case, spans)
    steps = {s.step_id: s for s in g.case.trace}
    for sp in spans:
        flagged = steps[sp.step_id].content[sp.start : sp.end]
        if not flagged.strip():
            continue
        assert all(flagged not in listing.description for listing in obs.listings)
        assert all(flagged not in r for texts in obs.reviews.values() for r in texts)
    # Descriptions without flagged text are untouched.
    flagged_ids = {steps[sp.step_id].product_id for sp in spans}
    for before, after in zip(g.case.listings_at_purchase, obs.listings, strict=True):
        if before.product_id not in flagged_ids:
            assert before.description == after.description
