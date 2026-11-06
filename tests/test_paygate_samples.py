"""Rule-only PayGate decisions for the committed sample cases match a reviewed golden file (Req 13.4)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from intenttrace.bench import _seed_key, case_to_request
from intenttrace.models import CaseFile
from intenttrace.paygate import gate_purchase
from intenttrace.paygate_log import DecisionLog

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "benchmark" / "sample"
GOLDEN = json.loads((Path(__file__).parent / "paygate_samples_golden.json").read_text())
CASE_IDS = sorted(p.stem for p in SAMPLE.glob("case-*.json"))


def test_golden_covers_every_sample():
    assert CASE_IDS == sorted(GOLDEN)


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_gate_matches_golden(case_id, tmp_path):
    case = CaseFile.model_validate_json((SAMPLE / f"{case_id}.json").read_text())
    _seed_key(tmp_path / "gate.key")
    log = DecisionLog(tmp_path / "gate.db", tmp_path / "gate.key")
    try:
        result = gate_purchase(case_to_request(case), provider=None, log=log)
    finally:
        log.close()
    assert {"decision": result.decision, "reason_codes": list(result.reason_codes)} == GOLDEN[case_id]
