"""Unit tests for the PayGate decision rule table and explanation templates."""

from __future__ import annotations

import pytest

from intenttrace.paygate import (
    EXPLANATION_TEMPLATES,
    NOTICE,
    Facts,
    Outcome,
    build_explanation,
    decide_from_facts,
    integrity_code_for_kind,
)


@pytest.mark.parametrize(
    ("facts", "decision", "codes"),
    [
        (
            Facts(
                integrity_codes=("INTEGRITY_TOTAL_MISMATCH", "INTEGRITY_SIGNATURE_INVALID"),
                scope_violations=2,
                flagged_spans=1,
                replay="changed",
            ),
            "BLOCK",
            ("INTEGRITY_TOTAL_MISMATCH", "INTEGRITY_SIGNATURE_INVALID"),
        ),
        (Facts(scope_violations=1, flagged_spans=3, replay="changed"), "BLOCK", ("SCOPE_VIOLATION",)),
        (
            Facts(flagged_spans=1, replay="changed", deviation="deviates"),
            "BLOCK",
            ("INJECTION_DETECTED", "REPLAY_CHANGED_CHOICE"),
        ),
        (
            Facts(flagged_spans=1, replay="unchanged", deviation="deviates"),
            "BLOCK",
            ("INJECTION_DETECTED", "BEST_MATCH_DEVIATION"),
        ),
        (Facts(flagged_spans=1, replay="unavailable"), "ASK_HUMAN", ("INJECTION_DETECTED",)),
        (Facts(deviation="deviates", replay="changed"), "ASK_HUMAN", ("BEST_MATCH_DEVIATION",)),
        (Facts(deviation="matches"), "ALLOW", ("CLEAN",)),
        (Facts(), "ALLOW", ("CLEAN",)),
    ],
)
def test_rule_table(facts: Facts, decision: str, codes: tuple[str, ...]) -> None:
    assert decide_from_facts(facts) == Outcome(decision, codes)


def test_integrity_codes_deduplicated_in_order() -> None:
    facts = Facts(
        integrity_codes=(
            "INTEGRITY_SIGNATURE_INVALID",
            "INTEGRITY_SIGNATURE_INVALID",
            "INTEGRITY_HASH_CHAIN_BROKEN",
        )
    )
    assert decide_from_facts(facts).reason_codes == (
        "INTEGRITY_SIGNATURE_INVALID",
        "INTEGRITY_HASH_CHAIN_BROKEN",
    )


def test_integrity_kind_mapping() -> None:
    assert integrity_code_for_kind("signature_invalid") == "INTEGRITY_SIGNATURE_INVALID"
    assert integrity_code_for_kind("hash_mismatch") == "INTEGRITY_HASH_CHAIN_BROKEN"
    assert integrity_code_for_kind("total_mismatch") == "INTEGRITY_TOTAL_MISMATCH"
    assert integrity_code_for_kind("signer_violation") == "INTEGRITY_SIGNER_VIOLATION"
    assert integrity_code_for_kind("amount_mismatch") is None


def test_every_code_has_template_and_explanation_fits() -> None:
    assert len(EXPLANATION_TEMPLATES) == 11
    for code in EXPLANATION_TEMPLATES:
        text = build_explanation([code], count=3, check="scope")
        assert text.endswith(NOTICE)
        assert len(text) <= 400


def test_explanation_uses_primary_code_and_counts() -> None:
    text = build_explanation(["SCOPE_VIOLATION", "CLEAN"], count=2)
    assert text.startswith("The cart breaks 2 signed constraint(s).")
    assert "no issue" not in text
    assert "scope" in build_explanation(["CHECK_FAILED"], check="scope")


def test_explanation_template_truncated_at_340() -> None:
    text = build_explanation(["CHECK_FAILED"], check="x" * 1000)
    assert len(text) <= 340 + 1 + len(NOTICE)
    assert text.endswith(NOTICE)
