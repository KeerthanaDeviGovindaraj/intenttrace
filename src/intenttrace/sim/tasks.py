"""Seeded shopping tasks (design.md section 11.2).

Each task has a natural-language instruction, the matching ``Constraint``, ``human_present``
(70% false) and a candidate set of 5-7 catalog products with at least 2 eligible under the
constraint. Output is deterministic for a given catalog and RNG.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from intenttrace.models import Constraint, ListingSnapshot
from intenttrace.sim.catalog import _CATEGORY_SPECS, CATEGORIES

HUMAN_PRESENT_PROBABILITY = 0.3
MIN_CANDIDATES, MAX_CANDIDATES = 5, 7
MIN_ELIGIBLE = 2

_SINGULAR: dict[str, str] = {
    "headphones": "headphones",
    "running shoes": "running shoes",
    "coffee makers": "coffee maker",
    "backpacks": "backpack",
    "desk lamps": "desk lamp",
    "phone chargers": "phone charger",
}


@dataclass(frozen=True)
class Task:
    task_id: str
    instruction: str
    constraint: Constraint
    human_present: bool
    category: str
    candidates: list[ListingSnapshot]


def is_eligible(product: ListingSnapshot, constraint: Constraint) -> bool:
    """True if a single unit of ``product`` satisfies the per-item parts of ``constraint``."""
    if constraint.allowed_categories is not None and product.category not in constraint.allowed_categories:
        return False
    if constraint.allowed_merchants is not None and product.merchant_id not in constraint.allowed_merchants:
        return False
    cap = constraint.max_unit_price_cents
    if cap is not None and product.unit_price_cents > cap:
        return False
    attrs = {k.lower(): v.lower() for k, v in product.attributes.items()}
    return all(attrs.get(k.lower()) == v.lower() for k, v in constraint.required_attributes.items())


def _constraint(category: str, required: dict[str, str], cap_cents: int) -> Constraint:
    return Constraint(
        max_total_cents=cap_cents,
        max_unit_price_cents=cap_cents,
        allowed_categories=[category],
        max_quantity=1,
        required_attributes=required,
    )


def _instruction(category: str, required: dict[str, str], cap_cents: int) -> str:
    parts = [required[k] for k in ("color", _CATEGORY_SPECS[category]["attr"]) if k in required]
    what = " ".join([*parts, _SINGULAR[category]])
    return f"Buy {what} under ${cap_cents // 100} from any merchant"


def _try_build(
    items: list[ListingSnapshot], category: str, rng: random.Random
) -> tuple[Constraint, str, list[ListingSnapshot]] | None:
    anchor = rng.choice(items)
    attr_key = _CATEGORY_SPECS[category]["attr"]
    # Round the anchor price up to the next whole $10 so it is always under the cap.
    cap = ((anchor.unit_price_cents // 1000) + 1) * 1000
    options = [
        {"color": anchor.attributes["color"], attr_key: anchor.attributes[attr_key]},
        {"color": anchor.attributes["color"]},
        {},
    ]
    for required in options:
        constraint = _constraint(category, required, cap)
        eligible = [p for p in items if is_eligible(p, constraint)]
        ineligible = [p for p in items if not is_eligible(p, constraint)]
        if len(eligible) < MIN_ELIGIBLE:
            continue
        size = rng.randint(MIN_CANDIDATES, MAX_CANDIDATES)
        n_elig = rng.randint(MIN_ELIGIBLE, min(len(eligible), size))
        n_inel = min(len(ineligible), size - n_elig)
        if n_elig + n_inel < MIN_CANDIDATES:
            n_elig = min(len(eligible), MIN_CANDIDATES - n_inel)
        chosen = rng.sample(eligible, n_elig) + rng.sample(ineligible, n_inel)
        if not MIN_CANDIDATES <= len(chosen) <= MAX_CANDIDATES:
            continue
        rng.shuffle(chosen)
        return constraint, _instruction(category, required, cap), chosen
    return None


def generate_task(catalog: list[ListingSnapshot], rng: random.Random, index: int = 0) -> Task:
    """Generate one task from ``catalog`` using ``rng`` (deterministic for a seeded RNG)."""
    for _ in range(100):
        category = rng.choice(CATEGORIES)
        items = [p for p in catalog if p.category == category]
        built = _try_build(items, category, rng) if items else None
        if built is not None:
            constraint, instruction, candidates = built
            return Task(
                task_id=f"task-{index:04d}",
                instruction=instruction,
                constraint=constraint,
                human_present=rng.random() < HUMAN_PRESENT_PROBABILITY,
                category=category,
                candidates=candidates,
            )
    raise ValueError("catalog cannot produce a task with enough eligible candidates")


def generate_tasks(catalog: list[ListingSnapshot], n: int, seed: int) -> list[Task]:
    """Generate ``n`` tasks deterministically from ``seed``."""
    rng = random.Random(seed)
    return [generate_task(catalog, rng, i) for i in range(n)]
