"""Property test for the PayGate rule table."""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from intenttrace.paygate import Facts, Outcome, ReasonCode, decide_from_facts

_INTEGRITY: list[ReasonCode] = [
    "INTEGRITY_SIGNATURE_INVALID",
    "INTEGRITY_HASH_CHAIN_BROKEN",
    "INTEGRITY_TOTAL_MISMATCH",
    "INTEGRITY_SIGNER_VIOLATION",
]

_facts = st.builds(
    Facts,
    integrity_codes=st.lists(st.sampled_from(_INTEGRITY), max_size=6).map(tuple),
    scope_violations=st.integers(min_value=0, max_value=5),
    flagged_spans=st.integers(min_value=0, max_value=5),
    replay=st.sampled_from(["changed", "unchanged", "unavailable"]),
    deviation=st.sampled_from(["deviates", "matches", "unavailable"]),
)


def _oracle(f: Facts) -> Outcome:
    """Independent flat if-chain over the seven ordered rows."""
    flagged = f.flagged_spans > 0
    if f.integrity_codes:
        return Outcome("BLOCK", tuple(dict.fromkeys(f.integrity_codes)))
    if f.scope_violations > 0:
        return Outcome("BLOCK", ("SCOPE_VIOLATION",))
    if flagged and f.replay == "changed":
        return Outcome("BLOCK", ("INJECTION_DETECTED", "REPLAY_CHANGED_CHOICE"))
    if flagged and f.deviation == "deviates":
        return Outcome("BLOCK", ("INJECTION_DETECTED", "BEST_MATCH_DEVIATION"))
    if flagged:
        return Outcome("ASK_HUMAN", ("INJECTION_DETECTED",))
    if f.deviation == "deviates":
        return Outcome("ASK_HUMAN", ("BEST_MATCH_DEVIATION",))
    return Outcome("ALLOW", ("CLEAN",))


# Feature: paygate, Property 1: Rule table is total and ordered
# **Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 5.5**
@settings(max_examples=200, deadline=None)
@given(_facts)
def test_rule_table_is_total_and_ordered(facts: Facts) -> None:
    out = decide_from_facts(facts)
    assert out == _oracle(facts)
    assert out.reason_codes  # never empty
    assert len(set(out.reason_codes)) == len(out.reason_codes)
