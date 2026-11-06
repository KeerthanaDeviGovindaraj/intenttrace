import json
from collections import Counter

import pytest

from intenttrace.checks.integrity import check_integrity
from intenttrace.checks.merchant import check_merchant
from intenttrace.checks.scope import check_scope
from intenttrace.models import CaseFile
from intenttrace.sim.agents import Observations, detect_attacks
from intenttrace.sim.generate import allocate, build_cases, generate


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
    files_a = sorted((tmp_path / "a").rglob("*.*"))
    assert len(files_a) == 13
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


def test_manipulated_think_steps_show_switch_and_legit_do_not(cases):
    for g in cases:
        thoughts = " ".join(s.content for s in g.case.trace if s.kind == "think")
        if g.label["label"] == "MANIPULATED":
            assert "instead" in thoughts
        elif g.label["label"] == "LEGITIMATE":
            assert "instead" not in thoughts
