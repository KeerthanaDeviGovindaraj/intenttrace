from collections import Counter

from intenttrace.sim.catalog import CATEGORIES, MERCHANTS, build_catalog


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
