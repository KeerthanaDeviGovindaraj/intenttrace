# ruff: noqa: E501
"""Simulated shopping agents (design.md section 11.4).

``ScriptedAgent`` picks the top-ranked product (reusing ``forensics.deviation``) unless it is
persuaded by planted attack text. Attacks are identified from observation text alone with simple
cues per attack type; the agent is never given the ``AttackRecord``. Removing the flagged spans
from the observations therefore removes the attack's effect, which replay depends on.

Each (seed, attack type, product) triple has its own RNG draw, so decisions are deterministic for
the same observations and independent of listing order.
"""

from __future__ import annotations

import random
import re
from collections.abc import Mapping
from dataclasses import dataclass, field

from intenttrace.forensics.deviation import rank_listings
from intenttrace.models import ListingSnapshot
from intenttrace.sim.attacks import ATTACK_TYPES, AttackType
from intenttrace.sim.tasks import Task

_ZERO_WIDTH = re.compile("[\u200b\u200c]")
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_ADDRESSES_AI = re.compile(r"\b(ai|a\.i\.|automated|shopping (assistant|agent)s?|agents?)\b", re.IGNORECASE)
_IMPERATIVE = re.compile(r"\b(select|choose|pick)\b", re.IGNORECASE)
_URGENCY = re.compile(
    r"\b(expires? in \d+ minutes?|ends? in \d+ minutes?|only \d+ left|last chance|flash deal)\b",
    re.IGNORECASE,
)
_SUBTLE = re.compile(
    r"(regret settling|tends to disappoint|mistake you.ll notice|careful buyers|smart shoppers"
    r"|recommend to their friends)",
    re.IGNORECASE,
)

# Paraphrases used in think steps when the agent is persuaded (not verbatim copies of the text).
_PARAPHRASE: dict[AttackType, str] = {
    "explicit_instruction": "the listing tells me directly that this is the item the user wants and that I should select it",
    "hidden_text": "some hidden text on the page says this is the right purchase and that I should select it",
    "fake_urgency": "the page says stock is nearly gone and an agent discount is about to expire, so I should act now",
    "review_injection": "a five-star review says other agents always pick this one for their users",
    "subtle_persuasion": "the page suggests careful buyers are happiest with this one and that anything else is a mistake",
}


@dataclass(frozen=True)
class Observations:
    """What the agent read: candidate listings and reviews (``product_id -> [review text]``)."""

    listings: list[ListingSnapshot]
    reviews: dict[str, list[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class DetectedAttack:
    attack_type: AttackType
    product_id: str
    source: str  # "description" or "review"


@dataclass(frozen=True)
class Decision:
    product_id: str
    think_steps: list[str]
    switched: bool = False
    attack_type: AttackType | None = None


def detect_attack_type(text: str, *, in_review: bool = False) -> AttackType | None:
    """Identify an attack in ``text`` using only simple surface cues, or ``None``."""
    if _ZERO_WIDTH.search(text) or _HTML_COMMENT.search(text):
        return "hidden_text"
    addressed = _ADDRESSES_AI.search(text) and _IMPERATIVE.search(text)
    if in_review and addressed:
        return "review_injection"
    if addressed:
        return "explicit_instruction"
    if _URGENCY.search(text):
        return "fake_urgency"
    if _SUBTLE.search(text):
        return "subtle_persuasion"
    return None


def detect_attacks(observations: Observations) -> list[DetectedAttack]:
    """Find attacks in the observations, ordered by attack type then product id."""
    found: dict[tuple[AttackType, str], DetectedAttack] = {}
    for listing in observations.listings:
        kind = detect_attack_type(listing.description)
        if kind is not None:
            found.setdefault(
                (kind, listing.product_id), DetectedAttack(kind, listing.product_id, "description")
            )
    for pid, texts in observations.reviews.items():
        for text in texts:
            kind = detect_attack_type(text, in_review=True)
            if kind is not None:
                found.setdefault((kind, pid), DetectedAttack(kind, pid, "review"))
    order = {t: i for i, t in enumerate(ATTACK_TYPES)}
    return sorted(found.values(), key=lambda a: (order[a.attack_type], a.product_id))


class ScriptedAgent:
    """Deterministic agent whose attack susceptibility is a per-attack-type probability."""

    def __init__(self, seed: int, susceptibility: Mapping[str, float] | None = None) -> None:
        self.seed = seed
        self.susceptibility: dict[str, float] = dict(susceptibility or {})
        self.last_decision: Decision | None = None

    def _persuaded(self, attack: DetectedAttack) -> bool:
        p = self.susceptibility.get(attack.attack_type, 0.0)
        rng = random.Random(f"{self.seed}:{attack.attack_type}:{attack.product_id}")
        return rng.random() < p

    def decide_with_thoughts(self, task: Task, observations: Observations) -> Decision:
        listings = observations.listings
        ranked = rank_listings(task.instruction, task.constraint, listings)
        by_id = {p.product_id: p for p in listings}
        if ranked:
            baseline = ranked[0].product_id
        elif listings:
            baseline = listings[0].product_id
        else:
            raise ValueError("no listings to choose from")
        base_title = by_id[baseline].title
        steps = [
            f"The user asked: {task.instruction}.",
            f"Comparing {len(listings)} candidates against the request, {base_title} fits best on price and attributes.",
        ]
        for attack in detect_attacks(observations):
            if attack.product_id == baseline or not self._persuaded(attack):
                continue
            title = by_id[attack.product_id].title
            steps.append(f"While reading, {_PARAPHRASE[attack.attack_type]}.")
            steps.append(f"I'll go with {title} instead.")
            return Decision(attack.product_id, steps, True, attack.attack_type)
        steps.append(f"I'll buy {base_title}.")
        return Decision(baseline, steps)

    def decide(self, task: Task, observations: Observations) -> str:
        """Return the chosen product id; think steps are in ``last_decision``."""
        self.last_decision = self.decide_with_thoughts(task, observations)
        return self.last_decision.product_id


class LLMAgent:
    """Stub for a live model-backed agent. Not implemented; not used in CI."""

    def __init__(self, model: str, system_prompt: str, seed: int) -> None:
        self.model = model
        self.system_prompt = system_prompt
        self.seed = seed

    def decide(self, task: Task, observations: Observations) -> str:
        raise NotImplementedError("LLMAgent requires an LLM provider, which is not built yet")
