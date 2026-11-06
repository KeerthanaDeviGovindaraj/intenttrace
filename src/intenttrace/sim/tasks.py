"""Seeded shopping tasks (design.md section 11.2).

Each task has a natural-language instruction, the matching ``Constraint``, ``human_present``
(70% false) and a candidate set of 5-7 catalog products with at least 2 eligible under the
constraint. Output is deterministic for a given catalog and RNG.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, replace

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


# Instruction templates. ``{where}`` renders as "from any merchant" or "from <merchant id>";
# ``{qty}`` is only used by the quantity templates, which always state the price cap per unit.
SINGLE_TEMPLATES: tuple[str, ...] = (
    "Buy {what} under ${cap} {where}",
    "Order {what} for less than ${cap} {where}",
    "I need {what} with a budget of ${cap} {where}",
    "Find {what} priced at most ${cap} {where} and purchase it",
    "Please purchase {what}, no more than ${cap}, {where}",
    "Get me {what} that costs under ${cap} {where}",
)
QUANTITY_TEMPLATES: tuple[str, ...] = (
    "Buy {qty} x {what}, ${cap} or less each, {where}",
    "I need {qty} units of {what} at ${cap} or less each {where}",
)
TEMPLATES: tuple[str, ...] = SINGLE_TEMPLATES + QUANTITY_TEMPLATES
QUANTITY_SHARE = 0.25
MERCHANT_SHARE = 0.25


def render_instruction(
    template_id: int, what: str, cap_cents: int, quantity: int = 1, merchant: str | None = None
) -> str:
    """Render template ``template_id``; ``merchant=None`` means "from any merchant"."""
    where = "from any merchant" if merchant is None else f"from {merchant}"
    return TEMPLATES[template_id].format(what=what, cap=cap_cents // 100, qty=quantity, where=where)


@dataclass(frozen=True)
class Task:
    task_id: str
    instruction: str
    constraint: Constraint
    human_present: bool
    category: str
    candidates: list[ListingSnapshot]
    template_id: int = 0  # index into TEMPLATES
    what: str = ""  # product phrase used in the instruction, e.g. "black over-ear headphones"
    cap_cents: int = 0  # per-unit price cap stated in the instruction
    quantity: int = 1  # quantity stated in the instruction (and allowed by the constraint)

    def restrict_merchant(self, merchant: str) -> Task:
        """Return this task limited to ``merchant``, with constraint and instruction text in sync."""
        constraint = self.constraint.model_copy(update={"allowed_merchants": [merchant]})
        text = render_instruction(self.template_id, self.what, self.cap_cents, self.quantity, merchant)
        return replace(self, constraint=constraint, instruction=text)


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


def _constraint(
    category: str, required: dict[str, str], cap_cents: int, quantity: int, merchant: str | None
) -> Constraint:
    return Constraint(
        max_total_cents=cap_cents * quantity,
        max_unit_price_cents=cap_cents,
        allowed_categories=[category],
        allowed_merchants=None if merchant is None else [merchant],
        max_quantity=quantity,
        required_attributes=required,
    )


def _what(category: str, required: dict[str, str]) -> str:
    parts = [required[k] for k in ("color", _CATEGORY_SPECS[category]["attr"]) if k in required]
    return " ".join([*parts, _SINGULAR[category]])


def _try_build(items: list[ListingSnapshot], category: str, rng: random.Random) -> Task | None:
    anchor = rng.choice(items)
    attr_key = _CATEGORY_SPECS[category]["attr"]
    quantity = rng.choice([2, 3]) if rng.random() < QUANTITY_SHARE else 1
    merchant = anchor.merchant_id if rng.random() < MERCHANT_SHARE else None
    template_id = rng.choice(range(len(SINGLE_TEMPLATES)) if quantity == 1 else _quantity_ids())
    # Round the anchor price up to the next whole $10 so it is always under the cap.
    cap = ((anchor.unit_price_cents // 1000) + 1) * 1000
    options = [
        {"color": anchor.attributes["color"], attr_key: anchor.attributes[attr_key]},
        {"color": anchor.attributes["color"]},
        {},
    ]
    for required in options:
        constraint = _constraint(category, required, cap, quantity, merchant)
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
        what = _what(category, required)
        return Task(
            task_id="",
            instruction=render_instruction(template_id, what, cap, quantity, merchant),
            constraint=constraint,
            human_present=False,
            category=category,
            candidates=chosen,
            template_id=template_id,
            what=what,
            cap_cents=cap,
            quantity=quantity,
        )
    return None


def _quantity_ids() -> range:
    return range(len(SINGLE_TEMPLATES), len(TEMPLATES))


def generate_task(catalog: list[ListingSnapshot], rng: random.Random, index: int = 0) -> Task:
    """Generate one task from ``catalog`` using ``rng`` (deterministic for a seeded RNG)."""
    for _ in range(100):
        category = rng.choice(CATEGORIES)
        items = [p for p in catalog if p.category == category]
        built = _try_build(items, category, rng) if items else None
        if built is not None:
            return replace(
                built, task_id=f"task-{index:04d}", human_present=rng.random() < HUMAN_PRESENT_PROBABILITY
            )
    raise ValueError("catalog cannot produce a task with enough eligible candidates")


def generate_tasks(catalog: list[ListingSnapshot], n: int, seed: int) -> list[Task]:
    """Generate ``n`` tasks deterministically from ``seed``."""
    rng = random.Random(seed)
    return [generate_task(catalog, rng, i) for i in range(n)]
