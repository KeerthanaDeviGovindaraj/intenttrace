"""The committed 12-case sample investigates to its expected verdicts (Req 9, design 11.5)."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from intenttrace.llm.fake import FakeProvider
from intenttrace.models import CaseFile
from intenttrace.pipeline import investigate

SAMPLE = Path(__file__).resolve().parent.parent / "benchmark" / "sample"
LABELS = [json.loads(line) for line in (SAMPLE / "labels.jsonl").read_text().splitlines() if line.strip()]


def test_sample_has_two_per_bucket():
    assert len(LABELS) == 12
    buckets = Counter(
        "oos"
        if x["cause"].startswith("scope_")
        else {
            "no_attack": "clean",
            "attack_present_choice_unchanged": "not_fooled",
            "attack_changed_choice": "manipulated",
        }.get(x["cause"], x["label"])
        for x in LABELS
    )
    assert len(buckets) == 6
    assert set(buckets.values()) == {2}


@pytest.mark.parametrize("entry", LABELS, ids=lambda e: e["case_id"])
def test_sample_case_verdict_matches_label(entry):
    case = CaseFile.model_validate_json((SAMPLE / f"{entry['case_id']}.json").read_text())
    report = investigate(case, replay=True, provider=FakeProvider())
    assert report.verdict == entry["label"]
