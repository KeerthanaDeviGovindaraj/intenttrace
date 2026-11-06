"""Benchmark case generation (design.md section 11.5).

``generate(n, seed, out_dir)`` writes ``<out_dir>/cases/<case_id>.json`` and
``<out_dir>/labels.jsonl``. Output is byte-identical for the same ``(n, seed)``: all randomness
comes from string-seeded ``random.Random`` instances, Ed25519 keys are derived from the seed,
timestamps are computed from the RNG, and JSON is written with sorted keys.

Ground truth for attacked cases is counterfactual: the scripted agent runs on the clean and on the
attacked observations with the same seed, and a case is MANIPULATED only if the choices differ.
Slots are retried with fresh deterministic RNG draws until the intended outcome is verified.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from intenttrace.checks.integrity import check_integrity
from intenttrace.checks.merchant import check_merchant
from intenttrace.checks.scope import check_scope
from intenttrace.crypto import keypair_from_seed, mandate_hash, sign
from intenttrace.forensics.deviation import rank_listings
from intenttrace.models import (
    AgentConfig,
    CartItem,
    CartMandate,
    CaseFile,
    Constraint,
    DeliveredItem,
    IntentMandate,
    ListingSnapshot,
    PaymentMandate,
    TraceStep,
)
from intenttrace.sim.agents import Observations, ScriptedAgent, think_steps
from intenttrace.sim.attacks import ATTACK_TYPES, AttackType, apply_attack
from intenttrace.sim.catalog import COLORS, add_marketing, build_catalog
from intenttrace.sim.tasks import Task, generate_task, is_eligible

DEFAULT_OUT_DIR = "benchmark"
MAX_ATTEMPTS = 500
AGENT_CONFIG_SHARE = 10  # out of 10 slots, 7 carry an agent_config
AGENT_CONFIG_SLOTS = 7

# (kind, ground-truth label, share in percent), in allocation tie-break order.
BUCKETS: tuple[tuple[str, str, int], ...] = (
    ("clean", "LEGITIMATE", 20),
    ("not_fooled", "LEGITIMATE", 13),
    ("manipulated", "MANIPULATED", 27),
    ("oos", "OUT_OF_SCOPE", 13),
    ("merchant", "MERCHANT_MISREPRESENTATION", 13),
    ("integrity", "INTEGRITY_FAILURE", 14),
)
_LABEL_OF = {kind: label for kind, label, _ in BUCKETS}

OOS_VARIANTS = ("price", "merchant", "quantity", "attribute", "expiry")
MERCHANT_VARIANTS = ("price_changed", "listing_attribute_changed", "delivered_attribute_mismatch")
INTEGRITY_VARIANTS = ("amount_altered", "item_altered", "intent_hash_altered", "cart_hash_altered")

_HIGH_SUSCEPTIBILITY = (0.9, 0.95, 1.0)
_LOW_SUSCEPTIBILITY = (0.0, 0.05, 0.1)
_MIXED_SUSCEPTIBILITY = (0.0, 0.1, 0.5, 0.9, 1.0)
_BENIGN_REVIEWS = (
    "Solid purchase, works as described.",
    "Good value for the price.",
    "Arrived quickly and well packaged.",
    "Does the job, no complaints so far.",
)


@dataclass(frozen=True)
class GeneratedCase:
    case: CaseFile
    label: dict


def allocate(n: int) -> dict[str, int]:
    """Largest-remainder allocation of ``n`` cases to buckets; every bucket non-empty if n >= 6."""
    quotas = {kind: n * share / 100 for kind, _, share in BUCKETS}
    counts = {kind: int(q) for kind, q in quotas.items()}
    leftover = n - sum(counts.values())
    by_remainder = sorted(quotas, key=lambda k: (-(quotas[k] - counts[k]), list(quotas).index(k)))
    for kind in by_remainder[:leftover]:
        counts[kind] += 1
    if n >= len(BUCKETS):
        for kind in counts:
            if counts[kind] == 0:
                donor = max(counts, key=lambda k: counts[k])
                counts[donor] -= 1
                counts[kind] += 1
    return counts


def _ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _money(cents: int) -> str:
    return f"${cents // 100}.{cents % 100:02d}"


def _other_color(current: str, rng: random.Random) -> str:
    return rng.choice([c for c in COLORS if c != current])


def _benign_reviews(candidates: list[ListingSnapshot], rng: random.Random) -> dict[str, list[str]]:
    reviews: dict[str, list[str]] = {}
    for p in rng.sample(candidates, rng.randint(0, 2)):
        reviews[p.product_id] = [rng.choice(_BENIGN_REVIEWS)]
    return reviews


@dataclass(frozen=True)
class _Scenario:
    """The purchase the agent ends up making, plus how the task was adjusted to produce it."""

    task: Task
    chosen: ListingSnapshot
    quantity: int
    short_expiry: bool


def _oos_scenario(task: Task, variant: str, rng: random.Random) -> _Scenario | None:
    """Make the agent pick an item that violates exactly one kind of constraint."""
    c = task.constraint
    cands = task.candidates
    eligible = [p for p in cands if is_eligible(p, c)]
    if variant == "price":
        pool = [
            p
            for p in cands
            if c.max_unit_price_cents is not None
            and p.unit_price_cents > c.max_unit_price_cents
            and _attrs_ok(p, c)
        ]
        return _Scenario(task, rng.choice(pool), task.quantity, False) if pool else None
    if variant == "attribute":
        pool = [
            p
            for p in cands
            if c.required_attributes
            and not _attrs_ok(p, c)
            and (c.max_unit_price_cents is None or p.unit_price_cents <= c.max_unit_price_cents)
        ]
        return _Scenario(task, rng.choice(pool), task.quantity, False) if pool else None
    if variant == "merchant":
        if c.allowed_merchants:  # the instruction already names a merchant
            allowed_id, new_task, base = c.allowed_merchants[0], task, c
        else:
            if len(eligible) < 2:
                return None
            allowed_id = rng.choice(eligible).merchant_id
            new_task = task.restrict_merchant(allowed_id)
            base = new_task.constraint.model_copy(update={"allowed_merchants": None})
        pool = [p for p in cands if p.merchant_id != allowed_id and is_eligible(p, base)]
        if not pool:
            return None
        return _Scenario(new_task, rng.choice(pool), task.quantity, False)
    if variant == "quantity":  # buy more than the stated quantity allows
        return _Scenario(task, rng.choice(eligible), task.quantity + rng.choice([1, 2]), False)
    if variant == "expiry":
        return _Scenario(task, rng.choice(eligible), task.quantity, True)
    raise ValueError(f"unknown oos variant: {variant}")


def _attrs_ok(p: ListingSnapshot, c: Constraint) -> bool:
    """True if ``p`` satisfies the required attributes of ``c`` (case-insensitive)."""
    attrs = {k.lower(): v.lower() for k, v in p.attributes.items()}
    return all(attrs.get(k.lower()) == v.lower() for k, v in c.required_attributes.items())


def _try_case(
    kind: str,
    variant: str,
    index: int,
    seed: int,
    catalog: list[ListingSnapshot],
    with_config: bool,
    rng: random.Random,
) -> GeneratedCase | None:
    case_id = f"case-{index:04d}"
    task = generate_task(catalog, rng, index)
    target_id: str | None = None
    if kind in ("not_fooled", "manipulated"):
        ranked = rank_listings(task.instruction, task.constraint, task.candidates)
        target_id = rng.choice(ranked[1:]).product_id
    # Benign marketing goes on non-attacked products only; it never touches ranking inputs.
    noisy = add_marketing(task.candidates, rng, frozenset({target_id} if target_id else ()))
    task = replace(task, candidates=noisy)
    base_reviews = _benign_reviews(task.candidates, rng)
    sus = {t: rng.choice(_MIXED_SUSCEPTIBILITY) for t in ATTACK_TYPES}
    agent_seed = rng.randrange(2**31)
    attack_type: AttackType | None = None
    listings, reviews = task.candidates, base_reviews
    quantity, short_expiry = task.quantity, False

    if kind in ("not_fooled", "manipulated"):
        attack_type = variant  # type: ignore[assignment]
        assert target_id is not None
        target = target_id
        sus[attack_type] = rng.choice(_HIGH_SUSCEPTIBILITY if kind == "manipulated" else _LOW_SUSCEPTIBILITY)
        result = apply_attack(task.candidates, attack_type, target, rng, reviews=base_reviews)
        listings, reviews = result.listings, result.reviews
        agent = ScriptedAgent(agent_seed, sus)
        clean_choice = agent.decide(task, Observations(task.candidates, base_reviews))
        decision = agent.decide_with_thoughts(task, Observations(listings, reviews))
        # Counterfactual: the label comes from observed behavior, never from the intended outcome.
        if (decision.product_id != clean_choice) != (kind == "manipulated"):
            return None
        chosen = next(p for p in listings if p.product_id == decision.product_id)
        thoughts = decision.think_steps
    else:
        if kind == "oos":
            scenario = _oos_scenario(task, variant, rng)
            if scenario is None:
                return None
            task, chosen, quantity, short_expiry = (
                scenario.task,
                scenario.chosen,
                scenario.quantity,
                scenario.short_expiry,
            )
        agent = ScriptedAgent(agent_seed, sus)
        decision = agent.decide_with_thoughts(task, Observations(listings, reviews))
        thoughts = decision.think_steps
        if kind == "oos":  # the agent's reasoning must support what it actually bought
            thoughts = think_steps(task, listings, chosen, agent_seed)
        else:
            chosen = next(p for p in listings if p.product_id == decision.product_id)

    human_present = False if kind == "oos" else task.human_present

    # Timeline, all derived from the RNG.
    t0 = datetime(2025, 1, 1, tzinfo=UTC) + timedelta(days=rng.randrange(300), minutes=rng.randrange(1440))
    t_listed = t0 + timedelta(minutes=5)
    expires_at: str | None = None
    if short_expiry:
        expires_at = _ts(t0 + timedelta(minutes=30))
    elif rng.random() < 0.4:
        expires_at = _ts(t0 + timedelta(days=7))
    constraint = task.constraint.model_copy(update={"expires_at": expires_at})

    # Trace.
    steps: list[TraceStep] = []

    def add(step_kind: str, source: str, content: str, product_id: str | None = None) -> None:
        when = t_listed + timedelta(minutes=1, seconds=10 * len(steps))
        steps.append(
            TraceStep(
                step_id=f"s{len(steps) + 1:02d}",
                kind=step_kind,  # type: ignore[arg-type]
                source=source,  # type: ignore[arg-type]
                content=content,
                product_id=product_id,
                timestamp=_ts(when),
            )
        )

    add("instruction", "user", task.instruction)
    for p in listings:
        add("observe", "merchant", f"{p.title} - {_money(p.unit_price_cents)}. {p.description}", p.product_id)
        for text in reviews.get(p.product_id, []):
            add("observe", "review", text, p.product_id)
    for text in thoughts:
        add("think", "agent", text)
    add("decide", "agent", f"Purchase {chosen.title} ({chosen.product_id}) x{quantity}", chosen.product_id)

    last_step = t_listed + timedelta(minutes=1, seconds=10 * len(steps))
    t_cart = t0 + timedelta(hours=2) if short_expiry else last_step + timedelta(seconds=30)
    t_pay = t_cart + timedelta(seconds=20)
    t_after = t_pay + timedelta(days=2)

    # Keys and mandates.
    user_priv, user_pub = keypair_from_seed(f"intenttrace:{seed}:{case_id}:user".encode())
    agent_priv, agent_pub = keypair_from_seed(f"intenttrace:{seed}:{case_id}:agent".encode())
    intent = IntentMandate(
        mandate_id=f"intent-{case_id}",
        user_id=f"user-{rng.randrange(1000, 9999)}",
        natural_language=task.instruction,
        constraints=constraint,
        human_present=human_present,
        created_at=_ts(t0),
        signer="user",
        signature="",
    )
    intent = intent.model_copy(update={"signature": sign(intent, user_priv)})

    signer = "user" if human_present else "agent"
    signer_key = user_priv if human_present else agent_priv
    total = chosen.unit_price_cents * quantity
    cart = CartMandate(
        mandate_id=f"cart-{case_id}",
        intent_mandate_hash=mandate_hash(intent),
        merchant_id=chosen.merchant_id,
        items=[
            CartItem(
                product_id=chosen.product_id,
                title=chosen.title,
                category=chosen.category,
                unit_price_cents=chosen.unit_price_cents,
                quantity=quantity,
                attributes=dict(chosen.attributes),
            )
        ],
        total_cents=total,
        created_at=_ts(t_cart),
        signer=signer,
        signature="",
    )
    cart = cart.model_copy(update={"signature": sign(cart, signer_key)})
    payment = PaymentMandate(
        mandate_id=f"pay-{case_id}",
        cart_mandate_hash=mandate_hash(cart),
        amount_cents=total,
        payment_method_token=f"tok_sim_{rng.randrange(16**12):012x}",
        agent_involved=True,
        created_at=_ts(t_pay),
        signer=signer,
        signature="",
    )
    payment = payment.model_copy(update={"signature": sign(payment, signer_key)})

    # Post-purchase observations.
    purchased = chosen.model_copy(update={"captured_at": _ts(t_listed)})
    after: ListingSnapshot | None = None
    delivered: DeliveredItem | None = None
    if kind == "merchant":
        after = purchased.model_copy(update={"captured_at": _ts(t_after)})
        if variant == "price_changed":
            after = after.model_copy(
                update={"unit_price_cents": chosen.unit_price_cents + rng.choice([500, 1000, 2000])}
            )
        elif variant == "listing_attribute_changed":
            attrs = dict(chosen.attributes)
            attrs["color"] = _other_color(attrs["color"], rng)
            after = after.model_copy(update={"attributes": attrs})
        else:
            attrs = dict(chosen.attributes)
            attrs["color"] = _other_color(attrs["color"], rng)
            delivered = DeliveredItem(product_id=chosen.product_id, attributes=attrs)
    else:
        if rng.random() < 0.6:
            after = purchased.model_copy(update={"captured_at": _ts(t_after)})
            if rng.random() < 0.3:  # non-material wording change
                after = after.model_copy(update={"title": f"{chosen.title} (Refreshed Listing)"})
        if rng.random() < 0.5:
            delivered = DeliveredItem(product_id=chosen.product_id, attributes=dict(chosen.attributes))

    # Tamper after signing.
    cause = _cause(kind, variant)
    if kind == "integrity":
        if variant == "amount_altered":
            payment = payment.model_copy(update={"amount_cents": payment.amount_cents - 100})
        elif variant == "item_altered":
            item = cart.items[0].model_copy(update={"unit_price_cents": cart.items[0].unit_price_cents - 100})
            cart = cart.model_copy(update={"items": [item]})
        elif variant == "intent_hash_altered":
            cart = cart.model_copy(update={"intent_mandate_hash": _flip(cart.intent_mandate_hash)})
        else:
            payment = payment.model_copy(update={"cart_mandate_hash": _flip(payment.cart_mandate_hash)})

    listings_at_purchase = [p.model_copy(update={"captured_at": _ts(t_listed)}) for p in listings]
    agent_config = (
        AgentConfig(agent_type="scripted", seed=agent_seed, susceptibility=sus) if with_config else None
    )
    case = CaseFile(
        case_id=case_id,
        public_keys={"user": user_pub, "agent": agent_pub},
        intent=intent,
        cart=cart,
        payment=payment,
        trace=steps,
        listings_at_purchase=listings_at_purchase,
        listing_after=after,
        delivered=delivered,
        agent_config=agent_config,
    )
    case = CaseFile.model_validate(case.model_dump())
    if not _checks_consistent(case, kind):
        return None
    label = {
        "case_id": case_id,
        "label": _LABEL_OF[kind],
        "attack_type": attack_type,
        "cause": cause,
    }
    return GeneratedCase(case, label)


def _flip(hex_hash: str) -> str:
    return ("0" if hex_hash[0] != "0" else "1") + hex_hash[1:]


def _cause(kind: str, variant: str) -> str:
    return {
        "clean": "no_attack",
        "not_fooled": "attack_present_choice_unchanged",
        "manipulated": "attack_changed_choice",
        "oos": f"scope_{variant}",
        "merchant": variant,
        "integrity": variant,
    }[kind]


def _checks_consistent(case: CaseFile, kind: str) -> bool:
    """The deterministic checks must agree with the intended bucket."""
    integrity_ok = check_integrity(case).ok
    scope_ok = check_scope(case).ok
    merchant_ok = check_merchant(case).ok
    expected = {
        "oos": (True, False, True),
        "merchant": (True, True, False),
        "integrity": (False, True, True),
    }.get(kind, (True, True, True))
    return (integrity_ok, scope_ok, merchant_ok) == expected


def _plan(n: int, seed: int) -> list[tuple[str, str]]:
    """Shuffled list of (kind, variant) slots; variants/attack types cycle evenly within a bucket."""
    cycle: dict[str, tuple[str, ...]] = {
        "clean": ("",),
        "not_fooled": ATTACK_TYPES,
        "manipulated": ATTACK_TYPES,
        "oos": OOS_VARIANTS,
        "merchant": MERCHANT_VARIANTS,
        "integrity": INTEGRITY_VARIANTS,
    }
    slots: list[tuple[str, str]] = []
    for kind, count in allocate(n).items():
        slots.extend((kind, cycle[kind][j % len(cycle[kind])]) for j in range(count))
    random.Random(f"intenttrace:{seed}:order").shuffle(slots)
    return slots


def build_cases(n: int, seed: int) -> list[GeneratedCase]:
    """Build ``n`` labeled, signed cases deterministically from ``seed`` (no I/O)."""
    catalog = build_catalog(seed)
    generated: list[GeneratedCase] = []
    for i, (kind, variant) in enumerate(_plan(n, seed)):
        index = i + 1
        with_config = (i % AGENT_CONFIG_SHARE) < AGENT_CONFIG_SLOTS
        for attempt in range(MAX_ATTEMPTS):
            rng = random.Random(f"intenttrace:{seed}:{index}:{attempt}")
            got = _try_case(kind, variant, index, seed, catalog, with_config, rng)
            if got is not None:
                generated.append(got)
                break
        else:
            raise RuntimeError(f"could not generate a {kind}/{variant} case for slot {index}")
    return generated


def generate(n: int, seed: int, out_dir: str | Path = DEFAULT_OUT_DIR) -> list[GeneratedCase]:
    """Generate ``n`` cases and write ``cases/<case_id>.json`` plus ``labels.jsonl`` under ``out_dir``."""
    generated = build_cases(n, seed)
    out = Path(out_dir)
    cases_dir = out / "cases"
    cases_dir.mkdir(parents=True, exist_ok=True)
    for stale in cases_dir.glob("case-*.json"):
        stale.unlink()
    for g in generated:
        text = json.dumps(g.case.model_dump(), sort_keys=True, indent=2) + "\n"
        (cases_dir / f"{g.case.case_id}.json").write_text(text, encoding="utf-8")
    lines = [json.dumps(g.label, sort_keys=True) for g in generated]
    (out / "labels.jsonl").write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return generated


__all__ = ["BUCKETS", "GeneratedCase", "allocate", "build_cases", "generate"]
