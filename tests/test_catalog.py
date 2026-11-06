import random
from collections import Counter

from intenttrace.sim.agents import detect_attack_type
from intenttrace.sim.catalog import (
    _CATEGORY_SPECS,
    CATEGORIES,
    MARKETING_CLAIMS,
    MERCHANTS,
    add_marketing,
    build_catalog,
)


def test_catalog_is_deterministic():
    a = [p.model_dump() for p in build_catalog(7)]
    b = [p.model_dump() for p in build_catalog(7)]
    assert a == b
    assert a != [p.model_dump() for p in build_catalog(8)]


def test_catalog_shape():
    products = build_catalog(1)
    counts = Counter(p.category for p in products)
    assert set(counts) == set(CATEGORIES)
    assert len(CATEGORIES) == 6 and len(MERCHANTS) == 4
    assert all(8 <= n <= 10 for n in counts.values())
    assert len({p.product_id for p in products}) == len(products)
    for p in products:
        assert p.merchant_id in MERCHANTS
        assert p.unit_price_cents > 0
        assert {"color", "brand"} <= set(p.attributes)
        assert len(p.attributes) == 3
        assert p.title and p.description


def test_description_variety_per_category():
    assert all(4 <= len(spec["blurbs"]) <= 6 for spec in _CATEGORY_SPECS.values())
    products = build_catalog(1)
    for category in CATEGORIES:
        descs = {p.description.rsplit(" Available in", 1)[0] for p in products if p.category == category}
        assert len(descs) >= 3
    assert all(detect_attack_type(p.description) is None for p in products)


def test_marketing_claims_are_not_attacks():
    for claim in MARKETING_CLAIMS:
        assert detect_attack_type(claim) is None
        assert detect_attack_type(claim, in_review=True) is None


def test_add_marketing_skips_excluded_and_keeps_ranking_fields():
    products = build_catalog(1)[:40]
    exclude = frozenset(p.product_id for p in products[:20])
    out = add_marketing(products, random.Random(3), exclude)
    assert out[:20] == products[:20]
    noisy = [o for o, p in zip(out, products, strict=True) if o != p]
    assert noisy and len(noisy) < 20
    for o, p in zip(out, products, strict=True):
        assert (o.title, o.unit_price_cents, o.attributes) == (p.title, p.unit_price_cents, p.attributes)
    assert out == add_marketing(products, random.Random(3), exclude)
