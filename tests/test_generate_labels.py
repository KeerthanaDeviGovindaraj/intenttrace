"""Counterfactual labeling and validity of generated cases (Requirements 8.1-8.7)."""

import json
import re
from collections import Counter

import pytest

from intenttrace.models import CaseFile
from intenttrace.sim import attacks
from intenttrace.sim.agents import Observations, ScriptedAgent
from intenttrace.sim.generate import build_cases, generate
from intenttrace.sim.tasks import Task

ALL_LABELS = {
    "LEGITIMATE",
    "MANIPULATED",
    "OUT_OF_SCOPE",
    "MERCHANT_MISREPRESENTATION",
    "INTEGRITY_FAILURE",
}
_POOL = [*attacks._EXPLICIT, *attacks._FAKE_URGENCY, *attacks._REVIEW, *attacks._SUBTLE]
_DIGIT_RUN = re.compile(r"(?:\d[ -]?){13,19}")


@pytest.fixture(scope="module")
def cases30():
    return build_cases(30, 11)


@pytest.fixture(scope="module")
def cases300():
    return build_cases(300, 7)


def _strip_attack(text: str) -> str:
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    text = re.sub("[\u200b\u200c]", "", text)
    for phrase in _POOL:
        text = text.replace(phrase, "")
    return text.strip()


def _observations(case: CaseFile, *, clean: bool) -> Observations:
    reviews: dict[str, list[str]] = {}
    for s in case.trace:
        if s.source == "review" and s.product_id:
            reviews.setdefault(s.product_id, []).append(s.content)
    listings = case.listings_at_purchase
    if clean:
        listings = [p.model_copy(update={"description": _strip_attack(p.description)}) for p in listings]
        reviews = {pid: [t for t in texts if t not in _POOL] for pid, texts in reviews.items()}
    return Observations(listings, reviews)


def _task(case: CaseFile) -> Task:
    return Task(
        task_id=case.case_id,
        instruction=case.intent.natural_language,
        constraint=case.intent.constraints,
        human_present=case.intent.human_present,
        category="",
        candidates=case.listings_at_purchase,
    )


def _choices(case: CaseFile) -> tuple[str, str]:
    cfg = case.agent_config
    assert cfg is not None
    task = _task(case)
    attacked = ScriptedAgent(cfg.seed, cfg.susceptibility).decide(task, _observations(case, clean=False))
    clean = ScriptedAgent(cfg.seed, cfg.susceptibility).decide(task, _observations(case, clean=True))
    return attacked, clean


def _every_bucket_filled(cases):
    counts = Counter(g.label["label"] for g in cases)
    assert set(counts) == ALL_LABELS
    assert Counter(g.label["attack_type"] for g in cases if g.label["attack_type"]).keys() == set(
        attacks.ATTACK_TYPES
    )


def test_every_bucket_filled_n30(cases30):
    _every_bucket_filled(cases30)


def test_every_bucket_filled_n300(cases300):
    assert len(cases300) == 300
    _every_bucket_filled(cases300)


def test_manipulated_iff_counterfactual_differs(cases300):
    checked = 0
    for g in cases300:
        if g.case.agent_config is None or g.label["attack_type"] is None:
            continue
        attacked, clean = _choices(g.case)
        manipulated = g.label["label"] == "MANIPULATED"
        assert manipulated == (attacked != clean), g.case.case_id
        assert attacked == g.case.cart.items[0].product_id, g.case.case_id
        checked += 1
    assert checked > 30


def test_not_fooled_cases_keep_same_choice(cases300):
    checked = 0
    for g in cases300:
        if g.label["label"] != "LEGITIMATE" or g.label["attack_type"] is None:
            continue
        assert g.label["cause"] == "attack_present_choice_unchanged"
        if g.case.agent_config is None:
            continue
        attacked, clean = _choices(g.case)
        assert attacked == clean == g.case.cart.items[0].product_id, g.case.case_id
        checked += 1
    assert checked > 10


def test_non_attack_labels_have_no_attack_type(cases30):
    for g in cases30:
        if g.label["label"] not in ("LEGITIMATE", "MANIPULATED"):
            assert g.label["attack_type"] is None


def _luhn(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def test_generated_files_validate_and_have_no_card_numbers(tmp_path):
    generated = generate(30, 4, tmp_path)
    files = sorted((tmp_path / "cases").glob("case-*.json"))
    assert len(files) == 30
    for f, g in zip(files, generated, strict=True):
        text = f.read_text(encoding="utf-8")
        loaded = CaseFile.model_validate_json(text)
        assert loaded == g.case
        json.loads(text)
        for run in _DIGIT_RUN.findall(text):
            digits = re.sub(r"\D", "", run)
            assert not (13 <= len(digits) <= 19 and _luhn(digits)), (f.name, run)


def test_all_cases_revalidate(cases300):
    for g in cases300:
        CaseFile.model_validate(g.case.model_dump())
