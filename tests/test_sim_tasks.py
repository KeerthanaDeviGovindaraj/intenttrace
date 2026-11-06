from intenttrace.sim.catalog import build_catalog
from intenttrace.sim.tasks import generate_tasks, is_eligible


def test_task_invariants():
    catalog = build_catalog(1)
    ids = {p.product_id for p in catalog}
    for t in generate_tasks(catalog, 100, seed=7):
        assert 5 <= len(t.candidates) <= 7
        assert len({p.product_id for p in t.candidates}) == len(t.candidates)
        assert {p.product_id for p in t.candidates} <= ids
        assert all(p.category == t.category for p in t.candidates)
        assert sum(is_eligible(p, t.constraint) for p in t.candidates) >= 2
        assert t.instruction.startswith("Buy ") and "from any merchant" in t.instruction
        assert t.constraint.allowed_categories == [t.category]


def test_deterministic():
    catalog = build_catalog(1)
    assert generate_tasks(catalog, 20, seed=3) == generate_tasks(catalog, 20, seed=3)
    assert generate_tasks(catalog, 20, seed=3) != generate_tasks(catalog, 20, seed=4)


def test_human_present_mostly_false():
    tasks = generate_tasks(build_catalog(1), 1000, seed=5)
    frac_false = sum(not t.human_present for t in tasks) / len(tasks)
    assert 0.63 < frac_false < 0.77
