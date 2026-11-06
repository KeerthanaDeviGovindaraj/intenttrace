"""Property tests for gate_purchase (paygate design.md, Properties 4, 5 and 6).

Every call uses a temporary DecisionLog, so the user's database is never touched.
"""

from __future__ import annotations

import copy
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from hypothesis import HealthCheck, assume, given, settings
from strategies_paygate import signed_request

from intenttrace.forensics.detect import detect
from intenttrace.paygate import GateRequest, GateResult, gate_purchase, request_to_case
from intenttrace.paygate_log import DecisionLog

_SETTINGS = settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)


@contextmanager
def _temp_log() -> Iterator[DecisionLog]:
    with tempfile.TemporaryDirectory() as tmp:
        log = DecisionLog(Path(tmp) / "log.db")
        try:
            yield log
        finally:
            log.close()


def _gate(req: GateRequest | dict, **kwargs) -> GateResult:
    with _temp_log() as log:
        return gate_purchase(req, log=log, **kwargs)


def _early_blocked(result: GateResult) -> bool:
    """True when integrity or scope ended evaluation before later checks ran."""
    return any(c.startswith("INTEGRITY_") or c == "SCOPE_VIOLATION" for c in result.reason_codes)


# Feature: paygate, Property 4: Determinism and input independence
@_SETTINGS
@given(signed_request())
def test_property_4_determinism_and_input_independence(req: GateRequest) -> None:
    """**Validates: Requirements 3.10, 6.2, 4.6**"""
    as_dict = req.model_dump()
    model_before = req.model_copy(deep=True)
    dict_before = copy.deepcopy(as_dict)

    from_model = _gate(req)
    from_dict = _gate(as_dict)

    assert from_model.record_id is not None
    assert from_dict.record_id is not None
    assert from_model.model_copy(update={"record_id": None}) == from_dict.model_copy(
        update={"record_id": None}
    )
    assert req == model_before
    assert as_dict == dict_before


# Feature: paygate, Property 5: Highlighted spans are well formed
@_SETTINGS
@given(signed_request())
def test_property_5_highlighted_spans_are_well_formed(req: GateRequest) -> None:
    """**Validates: Requirements 2.3, 4.2**

    Applies when integrity and scope pass. Integrity or scope BLOCKs stop before
    detection runs (Req 3.8), so those examples are discarded.
    """
    result = _gate(req)
    assume(not _early_blocked(result))
    texts = {str(c.item_id): c.text for c in req.content}

    for span in result.spans:
        assert span.item_id in texts
        assert 0 <= span.start < span.end <= len(texts[span.item_id])

    detected = detect(request_to_case(req), None).spans
    expected = {(s.step_id, s.start, s.end, s.rule_id or s.method or "unknown") for s in detected}
    actual = {(s.item_id, s.start, s.end, s.rule_id) for s in result.spans}
    assert actual == expected


# Feature: paygate, Property 6: Skipped checks are reported
@_SETTINGS
@given(signed_request())
def test_property_6_skipped_checks_are_reported(req: GateRequest) -> None:
    """**Validates: Requirements 1.2, 3.9, 6.5**

    Applies when integrity and scope pass. Integrity or scope BLOCKs stop before
    replay and deviation run (Req 3.8), so those examples are discarded.
    """
    for replay in (True, False):
        result = _gate(req, replay=replay)
        assume(not _early_blocked(result))
        skipped = result.skipped_checks
        if not replay or req.agent_config is None:
            assert any(s.startswith("replay") for s in skipped), (replay, skipped)
        if not req.listings:
            assert any(s.startswith("deviation") for s in skipped), skipped
