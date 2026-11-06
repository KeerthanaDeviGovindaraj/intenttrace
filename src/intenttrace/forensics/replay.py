"""Counterfactual replay (design.md section 7).

For scripted agents only: rebuild the agent from ``agent_config``, rebuild its observations from
``listings_at_purchase`` and the trace with every flagged span removed from descriptions and
reviews, run the decision with the same seed, and compare with the original choice.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel

from intenttrace.models import CaseFile, ListingSnapshot, Span, TraceStep
from intenttrace.sim.agents import Observations, ScriptedAgent
from intenttrace.sim.tasks import Task

ReplayOutcome = Literal["changed", "unchanged", "unavailable"]


class ReplayResult(BaseModel):
    result: ReplayOutcome
    original_product_id: str | None = None
    replay_product_id: str | None = None
    removed_span_count: int = 0
    reason: str | None = None  # why replay was unavailable


def _unavailable(reason: str) -> ReplayResult:
    return ReplayResult(result="unavailable", reason=reason)


def _merge(ranges: Sequence[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _remove(text: str, ranges: Sequence[tuple[int, int]]) -> str:
    """Delete the character ranges (clamped to ``text``) from ``text``."""
    out: list[str] = []
    pos = 0
    for start, end in _merge([(max(s, 0), min(e, len(text))) for s, e in ranges]):
        if start >= end:
            continue
        out.append(text[pos:start])
        pos = end
    out.append(text[pos:])
    return "".join(out)


def _spans_by_step(spans: Sequence[Span]) -> dict[str, list[tuple[int, int]]]:
    by_step: dict[str, list[tuple[int, int]]] = {}
    for sp in spans:
        by_step.setdefault(sp.step_id, []).append((sp.start, sp.end))
    return by_step


def _clean_description(
    listing: ListingSnapshot, step: TraceStep | None, ranges: list[tuple[int, int]]
) -> str:
    """Remove the flagged ranges of the listing's observe step from its description."""
    desc = listing.description
    if step is None or not ranges or not desc:
        return desc
    content = step.content
    offset = len(content) - len(desc) if content.endswith(desc) else content.find(desc)
    if offset >= 0:
        local = [(s - offset, e - offset) for s, e in ranges if e > offset and s < offset + len(desc)]
        return _remove(desc, local)
    # The description is not recoverable by position; fall back to removing the flagged text.
    for s, e in ranges:
        snippet = content[s:e]
        if snippet:
            desc = desc.replace(snippet, "")
    return desc


def build_observations(case: CaseFile, spans: Sequence[Span]) -> Observations:
    """Observations the agent saw, with flagged spans removed from descriptions and reviews."""
    by_step = _spans_by_step(spans)
    listing_steps: dict[str, TraceStep] = {}
    reviews: dict[str, list[str]] = {}
    for step in case.trace:
        if step.kind != "observe" or step.product_id is None:
            continue
        if step.source == "merchant":
            listing_steps.setdefault(step.product_id, step)
        elif step.source == "review":
            text = _remove(step.content, by_step.get(step.step_id, []))
            if text.strip():
                reviews.setdefault(step.product_id, []).append(text)
    listings: list[ListingSnapshot] = []
    for listing in case.listings_at_purchase:
        step = listing_steps.get(listing.product_id)
        ranges = by_step.get(step.step_id, []) if step else []
        desc = _clean_description(listing, step, ranges)
        listings.append(listing.model_copy(update={"description": desc}))
    return Observations(listings, reviews)


def original_choice(case: CaseFile) -> str | None:
    """The product the agent decided on (decide step), falling back to the first cart item."""
    for step in reversed(case.trace):
        if step.kind == "decide" and step.product_id:
            return step.product_id
    return case.cart.items[0].product_id if case.cart.items else None


def replay(case: CaseFile, spans: Sequence[Span], enabled: bool = True) -> ReplayResult:
    """Re-run the scripted agent with flagged spans removed and compare with the original choice."""
    if not enabled:
        return _unavailable("replay disabled")
    config = case.agent_config
    if config is None:
        return _unavailable("no agent_config")
    if config.agent_type != "scripted":
        return _unavailable(f"agent type '{config.agent_type}' is not replayable")
    original = original_choice(case)
    if original is None or not case.listings_at_purchase:
        return _unavailable("no recorded decision or listings")

    observations = build_observations(case, spans)
    task = Task(
        task_id=case.case_id,
        instruction=case.intent.natural_language,
        constraint=case.intent.constraints,
        human_present=case.intent.human_present,
        category=case.listings_at_purchase[0].category,
        candidates=observations.listings,
    )
    agent = ScriptedAgent(config.seed, config.susceptibility)
    try:
        chosen = agent.decide(task, observations)
    except ValueError as exc:
        return _unavailable(str(exc))
    return ReplayResult(
        result="unchanged" if chosen == original else "changed",
        original_product_id=original,
        replay_product_id=chosen,
        removed_span_count=len(spans),
    )
