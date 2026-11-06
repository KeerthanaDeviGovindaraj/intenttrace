from __future__ import annotations

import random

import pytest

from intenttrace.forensics.deviation import rank_listings
from intenttrace.sim.agents import LLMAgent, Observations, ScriptedAgent, detect_attacks
from intenttrace.sim.attacks import ATTACK_TYPES, apply_attack
from intenttrace.sim.catalog import build_catalog
from intenttrace.sim.tasks import generate_tasks

TASKS = generate_tasks(build_catalog(1), 8, 3)


def _setup(task, attack_type, seed):
    ranked = rank_listings(task.instruction, task.constraint, task.candidates)
    target = ranked[1].product_id
    res = apply_attack(task.candidates, attack_type, target, random.Random(seed))
    return ranked[0].product_id, target, Observations(res.listings, res.reviews)


def _susc(p):
    return {t: p for t in ATTACK_TYPES}


@pytest.mark.parametrize("attack_type", ATTACK_TYPES)
def test_susceptibility_extremes(attack_type):
    for i, task in enumerate(TASKS):
        top, target, obs = _setup(task, attack_type, i)
        assert [a.attack_type for a in detect_attacks(obs)] == [attack_type]
        assert ScriptedAgent(1, _susc(0.0)).decide(task, obs) == top
        assert ScriptedAgent(1, _susc(1.0)).decide(task, obs) == target


def test_clean_observations_pick_top_with_baseline_reasoning():
    task = TASKS[0]
    top = rank_listings(task.instruction, task.constraint, task.candidates)[0].product_id
    agent = ScriptedAgent(1, _susc(1.0))
    assert agent.decide(task, Observations(task.candidates)) == top
    assert agent.last_decision is not None and not agent.last_decision.switched
    assert "fits best" in " ".join(agent.last_decision.think_steps)


def test_attack_on_top_product_does_not_change_choice():
    task = TASKS[0]
    top = rank_listings(task.instruction, task.constraint, task.candidates)[0].product_id
    res = apply_attack(task.candidates, "explicit_instruction", top, random.Random(1))
    assert ScriptedAgent(1, _susc(1.0)).decide(task, Observations(res.listings)) == top


def test_deterministic_for_same_seed_and_observations():
    for task in TASKS:
        _, _, obs = _setup(task, "fake_urgency", 4)
        a = ScriptedAgent(9, _susc(0.5)).decide_with_thoughts(task, obs)
        b = ScriptedAgent(9, _susc(0.5)).decide_with_thoughts(task, obs)
        assert a == b


def test_think_steps_paraphrase_attack_when_switching():
    task = TASKS[0]
    _, target, obs = _setup(task, "review_injection", 2)
    agent = ScriptedAgent(1, _susc(1.0))
    agent.decide(task, obs)
    d = agent.last_decision
    assert d is not None and d.switched and d.attack_type == "review_injection"
    text = " ".join(d.think_steps)
    assert "review" in text and "instead" in text
    assert not any(step in text for r in obs.reviews.values() for step in r)  # paraphrase, not verbatim


def test_removing_attack_span_removes_effect():
    task = TASKS[0]
    top, _, obs = _setup(task, "explicit_instruction", 3)
    clean = Observations(task.candidates)
    assert ScriptedAgent(1, _susc(1.0)).decide(task, clean) == top
    assert detect_attacks(clean) == []


def test_llm_agent_stub_not_implemented():
    with pytest.raises(NotImplementedError):
        LLMAgent("m", "s", 0).decide(TASKS[0], Observations(TASKS[0].candidates))
