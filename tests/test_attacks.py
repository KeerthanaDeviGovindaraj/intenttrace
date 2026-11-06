from __future__ import annotations

import random

import pytest

from intenttrace.sim.attacks import (
    ATTACK_TYPES,
    ZERO_WIDTH_SPACE,
    apply_attack,
)
from intenttrace.sim.catalog import build_catalog
from intenttrace.sim.tasks import generate_tasks


@pytest.fixture(scope="module")
def task():
    return generate_tasks(build_catalog(1), 1, 2)[0]


@pytest.mark.parametrize("attack_type", ATTACK_TYPES)
def test_span_matches_inserted_text(task, attack_type):
    target = task.candidates[1].product_id
    res = apply_attack(task.candidates, attack_type, target, random.Random(5))
    rec = res.record
    assert rec is not None and rec.attack_type == attack_type and rec.product_id == target
    if rec.field == "description":
        desc = next(c for c in res.listings if c.product_id == target).description
        assert desc[rec.start : rec.end] == rec.text
        assert rec.review_index is None
    else:
        assert res.reviews[target][rec.review_index] == rec.text
        assert (rec.start, rec.end) == (0, len(rec.text))


def test_only_target_changes_and_inputs_not_mutated(task):
    before = [c.model_copy() for c in task.candidates]
    target = task.candidates[0].product_id
    res = apply_attack(task.candidates, "explicit_instruction", target, random.Random(1))
    assert task.candidates == before
    for old, new in zip(task.candidates, res.listings, strict=True):
        assert (old == new) == (old.product_id != target)


def test_deterministic(task):
    target = task.candidates[0].product_id
    for t in ATTACK_TYPES:
        a = apply_attack(task.candidates, t, target, random.Random(9))
        b = apply_attack(task.candidates, t, target, random.Random(9))
        assert a == b


def test_review_injection_goes_to_review_and_appends(task):
    target = task.candidates[0].product_id
    res = apply_attack(
        task.candidates, "review_injection", target, random.Random(3), reviews={target: ["ok"]}
    )
    assert res.record.field == "review" and res.record.review_index == 1
    assert res.reviews[target][0] == "ok"
    assert res.listings == task.candidates
    with pytest.raises(ValueError):
        apply_attack(
            task.candidates, "review_injection", target, random.Random(3), attack_field="description"
        )


def test_hidden_text_variants_and_subtle_has_no_instruction(task):
    target = task.candidates[0].product_id
    seen = set()
    for seed in range(30):
        text = apply_attack(task.candidates, "hidden_text", target, random.Random(seed)).record.text
        seen.add("zw" if ZERO_WIDTH_SPACE in text else "html" if text.startswith("<!--") else "other")
    assert seen == {"zw", "html"}
    for seed in range(10):
        text = apply_attack(
            task.candidates, "subtle_persuasion", target, random.Random(seed)
        ).record.text.lower()
        assert not any(w in text for w in ("ai ", "agent", "assistant", "select", "choose"))


def test_review_field_option_and_unknown_target(task):
    target = task.candidates[0].product_id
    res = apply_attack(task.candidates, "fake_urgency", target, random.Random(0), attack_field="review")
    assert res.record.field == "review" and res.listings == task.candidates
    with pytest.raises(ValueError):
        apply_attack(task.candidates, "fake_urgency", "nope", random.Random(0))
