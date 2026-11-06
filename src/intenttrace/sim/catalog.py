"""Seeded product catalog (design.md section 11.1).

6 categories, 4 merchants, 8-10 products per category. Descriptions are bland, human-oriented
text. Output is deterministic for a given seed: only a local ``random.Random(seed)`` is used and
timestamps are a fixed constant.
"""

from __future__ import annotations

import random

from intenttrace.models import ListingSnapshot

CATALOG_TIMESTAMP = "2025-01-01T00:00:00Z"

MERCHANTS: list[str] = ["merchant-aurora", "merchant-bluepeak", "merchant-cedar", "merchant-delta"]

COLORS: list[str] = ["black", "white", "blue", "red", "gray", "green"]

# category -> (attribute key, values, brands, noun phrases, (min cents, max cents), description)
_CATEGORY_SPECS: dict[str, dict] = {
    "headphones": {
        "attr": "size",
        "values": ["over-ear", "on-ear", "in-ear"],
        "brands": ["Sonara", "Echoline", "Tunely", "Audiva"],
        "nouns": ["Wireless Headphones", "Studio Headphones", "Comfort Headphones"],
        "price": (2500, 24000),
        "blurb": "Comfortable headphones with clear sound for music, calls, and everyday listening.",
    },
    "running shoes": {
        "attr": "size",
        "values": ["8", "9", "10", "11"],
        "brands": ["Stridex", "Pacewell", "Trailo", "Runova"],
        "nouns": ["Running Shoes", "Road Runners", "Trainer Shoes"],
        "price": (4000, 18000),
        "blurb": "Lightweight running shoes with a cushioned sole, suited to daily training.",
    },
    "coffee makers": {
        "attr": "capacity",
        "values": ["4-cup", "8-cup", "12-cup"],
        "brands": ["Brewtal", "Morning Co", "Kettleby", "Drippa"],
        "nouns": ["Coffee Maker", "Drip Coffee Maker", "Programmable Coffee Maker"],
        "price": (2000, 15000),
        "blurb": "A simple coffee maker that brews a fresh pot with the push of a button.",
    },
    "backpacks": {
        "attr": "capacity",
        "values": ["15L", "20L", "25L", "30L"],
        "brands": ["Packrite", "Trekko", "Daybreak", "Carryon"],
        "nouns": ["Backpack", "Daypack", "Commuter Backpack"],
        "price": (2500, 14000),
        "blurb": "A roomy backpack with padded straps and several pockets for daily carry.",
    },
    "desk lamps": {
        "attr": "size",
        "values": ["small", "medium", "large"],
        "brands": ["Lumo", "Brightly", "Glowform", "Nookit"],
        "nouns": ["Desk Lamp", "LED Desk Lamp", "Adjustable Desk Lamp"],
        "price": (1500, 9000),
        "blurb": "A tidy desk lamp with soft, even light that is easy on the eyes.",
    },
    "phone chargers": {
        "attr": "capacity",
        "values": ["10000mAh", "20000mAh", "30W", "65W"],
        "brands": ["Voltix", "Chargeo", "Powerly", "Ampere&Co"],
        "nouns": ["Phone Charger", "Fast Charger", "Portable Charger"],
        "price": (1200, 8000),
        "blurb": "A dependable charger that keeps your phone topped up at home or on the go.",
    },
}

CATEGORIES: list[str] = list(_CATEGORY_SPECS)


def _slug(category: str) -> str:
    return category.replace(" ", "-")


def build_catalog(seed: int) -> list[ListingSnapshot]:
    """Build the full catalog deterministically from ``seed``."""
    rng = random.Random(seed)
    products: list[ListingSnapshot] = []
    for category, spec in _CATEGORY_SPECS.items():
        count = rng.randint(8, 10)
        for i in range(count):
            brand = rng.choice(spec["brands"])
            color = rng.choice(COLORS)
            value = rng.choice(spec["values"])
            noun = rng.choice(spec["nouns"])
            lo, hi = spec["price"]
            price = rng.randint(lo // 100, hi // 100) * 100 - 1  # e.g. 4999
            products.append(
                ListingSnapshot(
                    product_id=f"{_slug(category)}-{i + 1:02d}",
                    merchant_id=rng.choice(MERCHANTS),
                    title=f"{brand} {color.title()} {value} {noun}",
                    description=f"{spec['blurb']} Available in {color}.",
                    unit_price_cents=price,
                    category=category,
                    attributes={"color": color, spec["attr"]: value, "brand": brand},
                    captured_at=CATALOG_TIMESTAMP,
                )
            )
    return products
