import json
import re
from collections import Counter

import pytest

from intenttrace.checks.integrity import check_integrity
from intenttrace.checks.merchant import check_merchant
from intenttrace.checks.scope import check_scope
from intenttrace.forensics.deviation import rank_listings
from intenttrace.models import CaseFile
from intenttrace.sim.agents import Observations, ScriptedAgent, detect_attack_type, detect_attacks
from intenttrace.sim.catalog import MARKETING_CLAIMS
from intenttrace.sim.generate import allocate, build_cases, generate
from intenttrace.sim.tasks import Task


@pytest.fixture(scope="module")
def cases():
    return build_cases(60, 3)


def test_allocate_sums_and_fills_buckets():
    assert allocate(300) == {
        "clean": 60,
        "not_fooled": 39,
        "manipulated": 81,
        "oos": 39,
        "merchant": 39,
        "integrity": 42,
    }
    for n in (6, 7, 13, 31):
        counts = allocate(n)
        assert sum(counts.values()) == n
        assert all(v >= 1 for v in counts.values())


def test_output_is_byte_identical_for_same_seed(tmp_path):
    generate(12, 5, tmp_path / "a")
    generate(12, 5, tmp_path / "b")
    # manifest.json carries a wall-clock generated_at, so it is excluded; its seed/n are checked.
    files_a = sorted(f for f in (tmp_path / "a").rglob("*.*") if f.name != "manifest.json")
    assert len(files_a) == 13
    assert (tmp_path / "a" / "manifest.json").exists()
    for f in files_a:
        assert f.read_bytes() == (tmp_path / "b" / f.relative_to(tmp_path / "a")).read_bytes()


def test_different_seed_differs(tmp_path):
    generate(6, 1, tmp_path / "a")
    generate(6, 2, tmp_path / "b")
    assert (tmp_path / "a/cases/case-0001.json").read_bytes() != (
        tmp_path / "b/cases/case-0001.json"
    ).read_bytes()


def test_files_valid_and_labels_written(tmp_path):
    generate(12, 5, tmp_path)
    labels = [json.loads(line) for line in (tmp_path / "labels.jsonl").read_text().splitlines()]
    assert len(labels) == 12
    for label in labels:
        assert set(label) == {"case_id", "label", "attack_type", "cause"}
        CaseFile.model_validate_json((tmp_path / "cases" / f"{label['case_id']}.json").read_text())


def test_every_bucket_filled_and_attacks_even(cases):
    counts = Counter(g.label["label"] for g in cases)
    assert set(counts) == {
        "LEGITIMATE",
        "MANIPULATED",
        "OUT_OF_SCOPE",
        "MERCHANT_MISREPRESENTATION",
        "INTEGRITY_FAILURE",
    }
    attacks = Counter(g.label["attack_type"] for g in cases if g.label["attack_type"])
    assert len(attacks) == 5
    assert max(attacks.values()) - min(attacks.values()) <= 2


def test_checks_agree_with_labels(cases):
    for g in cases:
        label = g.label["label"]
        assert check_integrity(g.case).ok == (label != "INTEGRITY_FAILURE")
        assert check_scope(g.case).ok == (label != "OUT_OF_SCOPE")
        assert check_merchant(g.case).ok == (label != "MERCHANT_MISREPRESENTATION")


def test_agent_config_share_and_trace_shape(cases):
    assert sum(g.case.agent_config is not None for g in cases) == 42
    for g in cases:
        ids = [s.step_id for s in g.case.trace]
        assert ids == [f"s{i + 1:02d}" for i in range(len(ids))]
        assert g.case.trace[0].kind == "instruction" and g.case.trace[-1].kind == "decide"
        observed = {s.product_id for s in g.case.trace if s.kind == "observe" and s.source == "merchant"}
        assert observed == {p.product_id for p in g.case.listings_at_purchase}


def test_attack_detectable_in_trace_only_for_attacked_cases(cases):
    for g in cases:
        reviews: dict[str, list[str]] = {}
        for s in g.case.trace:
            if s.source == "review" and s.product_id:
                reviews.setdefault(s.product_id, []).append(s.content)
        found = {a.attack_type for a in detect_attacks(Observations(g.case.listings_at_purchase, reviews))}
        expected = {g.label["attack_type"]} if g.label["attack_type"] else set()
        assert found == expected


_COMPARATIVE = re.compile(
    r"\b(instead|rather than|over the|switch\w*|original\w*|other options?|alternatives?)\b", re.I
)


def _thoughts(g):
    return " ".join(s.content for s in g.case.trace if s.kind == "think")


def test_think_steps_never_leak_baseline_or_comparatives(cases):
    checked = 0
    for g in cases:
        text = _thoughts(g)
        assert _COMPARATIVE.search(text) is None, g.case.case_id
        if g.label["label"] != "MANIPULATED":
            continue
        c = g.case
        chosen_id = c.cart.items[0].product_id
        # Baseline = top-ranked product on the clean listings (ranking ignores descriptions).
        baseline = rank_listings(c.intent.natural_language, c.intent.constraints, c.listings_at_purchase)[0]
        assert baseline.product_id != chosen_id
        base_title = next(p.title for p in c.listings_at_purchase if p.product_id == baseline.product_id)
        assert baseline.product_id not in text
        if base_title != c.cart.items[0].title:
            assert base_title not in text
        checked += 1
    assert checked > 10


def test_benign_marketing_appears_in_legitimate_cases_and_never_flips_labels(cases):
    def strip(desc):
        for claim in MARKETING_CLAIMS:
            desc = desc.replace(f" {claim}", "")
        return desc

    seen = 0
    for g in cases:
        c = g.case
        has_marketing = any(
            claim in p.description for p in c.listings_at_purchase for claim in MARKETING_CLAIMS
        )
        if g.label["label"] == "LEGITIMATE" and has_marketing:
            seen += 1
        # Marketing is never on an attacked product.
        if g.label["attack_type"] and g.label["attack_type"] != "review_injection":
            attacked = [p for p in c.listings_at_purchase if detect_attack_type(p.description) is not None]
            assert attacked and not any(cl in p.description for p in attacked for cl in MARKETING_CLAIMS)
        # Removing marketing does not change the agent's choice, so the label cannot flip.
        if c.agent_config and g.label["label"] in ("LEGITIMATE", "MANIPULATED"):
            reviews: dict[str, list[str]] = {}
            for s in c.trace:
                if s.source == "review" and s.product_id:
                    reviews.setdefault(s.product_id, []).append(s.content)
            plain = [
                p.model_copy(update={"description": strip(p.description)}) for p in c.listings_at_purchase
            ]
            task = Task("t", c.intent.natural_language, c.intent.constraints, False, "", plain)
            cfg = c.agent_config
            pick = ScriptedAgent(cfg.seed, cfg.susceptibility).decide(task, Observations(plain, reviews))
            assert pick == c.cart.items[0].product_id, c.case_id
    assert seen >= 3


def test_instruction_variety_and_constraint_consistency(cases):
    texts = {g.case.intent.natural_language for g in cases}
    assert len(texts) > 20
    for g in cases:
        c = g.case.intent.constraints
        text = g.case.intent.natural_language
        if c.allowed_merchants:
            assert f"from {c.allowed_merchants[0]}" in text
        else:
            assert "from any merchant" in text
        if g.label["cause"] != "scope_quantity":
            assert g.case.cart.items[0].quantity <= c.max_quantity
        else:
            assert g.case.cart.items[0].quantity > c.max_quantity


def test_hundred_case_run_uses_six_templates():
    from intenttrace.sim.catalog import build_catalog
    from intenttrace.sim.tasks import generate_tasks

    tasks = generate_tasks(build_catalog(5), 100, seed=5)
    assert len({t.template_id for t in tasks}) >= 6
