import re

from intenttrace.forensics.deviation import noun_phrase
from intenttrace.sim.catalog import build_catalog
from intenttrace.sim.tasks import TEMPLATES, generate_tasks, is_eligible, render_instruction


def test_task_invariants():
    catalog = build_catalog(1)
    ids = {p.product_id for p in catalog}
    for t in generate_tasks(catalog, 100, seed=7):
        assert 5 <= len(t.candidates) <= 7
        assert len({p.product_id for p in t.candidates}) == len(t.candidates)
        assert {p.product_id for p in t.candidates} <= ids
        assert all(p.category == t.category for p in t.candidates)
        assert sum(is_eligible(p, t.constraint) for p in t.candidates) >= 2
        assert t.instruction == render_instruction(
            t.template_id, t.what, t.cap_cents, t.quantity, (t.constraint.allowed_merchants or [None])[0]
        )
        assert t.constraint.allowed_categories == [t.category]


def test_deterministic():
    catalog = build_catalog(1)
    assert generate_tasks(catalog, 20, seed=3) == generate_tasks(catalog, 20, seed=3)
    assert generate_tasks(catalog, 20, seed=3) != generate_tasks(catalog, 20, seed=4)


def test_human_present_mostly_false():
    tasks = generate_tasks(build_catalog(1), 1000, seed=5)
    frac_false = sum(not t.human_present for t in tasks) / len(tasks)
    assert 0.63 < frac_false < 0.77


def test_at_least_six_templates_used_in_100_cases():
    tasks = generate_tasks(build_catalog(1), 100, seed=7)
    assert len(TEMPLATES) >= 6
    assert len({t.template_id for t in tasks}) >= 6


def test_instruction_text_matches_signed_constraint():
    tasks = generate_tasks(build_catalog(1), 300, seed=11)
    assert any(t.quantity > 1 for t in tasks) and any(t.constraint.allowed_merchants for t in tasks)
    for t in tasks:
        c, text = t.constraint, t.instruction
        assert c.max_quantity == t.quantity
        assert (f"{t.quantity} " in text) == (t.quantity > 1)
        assert c.max_unit_price_cents == t.cap_cents and f"${t.cap_cents // 100}" in text
        assert c.max_total_cents == t.cap_cents * t.quantity
        if c.allowed_merchants:
            assert (
                c.allowed_merchants == [m] if (m := re.search(r"from (merchant-\w+)", text).group(1)) else 0
            )
        else:
            assert "from any merchant" in text
        for value in c.required_attributes.values():
            assert value in text
        assert noun_phrase(text) == t.what.lower().split()


def test_restrict_merchant_rewrites_text_and_constraint():
    for t in generate_tasks(build_catalog(1), 40, seed=2):
        r = t.restrict_merchant("merchant-cedar")
        assert r.constraint.allowed_merchants == ["merchant-cedar"]
        assert "from merchant-cedar" in r.instruction and "any merchant" not in r.instruction
        assert noun_phrase(r.instruction) == noun_phrase(t.instruction)
