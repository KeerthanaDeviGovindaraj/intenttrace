"""Property tests for gate_purchase (paygate design.md, Properties 2 and 3).

Every call uses a temporary DecisionLog (own db and key file), so the user's db is never touched.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, get_args

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from strategies_paygate import mutated_request, signed_request

from intenttrace.paygate import NOTICE, ReasonCode, gate_purchase
from intenttrace.paygate_log import DecisionLog, _create_key

_SETTINGS = settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)

_CODES = set(get_args(ReasonCode))


@pytest.fixture(scope="module")
def gate_log(tmp_path_factory: pytest.TempPathFactory) -> Iterator[DecisionLog]:
    tmp = tmp_path_factory.mktemp("paygate_props")
    _create_key(tmp / "log.key")  # an explicit key file is never auto-created
    log = DecisionLog(tmp / "log.db", key_file=tmp / "log.key")
    yield log
    log.close()


_json_leaf = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(),
    st.floats(allow_nan=False, allow_infinity=False),
    st.text(max_size=20),
)
_json_value = st.recursive(
    _json_leaf,
    lambda kids: st.one_of(
        st.lists(kids, max_size=4),
        st.dictionaries(st.text(max_size=8), kids, max_size=4),
    ),
    max_leaves=12,
)


class _Opaque:
    def __repr__(self) -> str:
        raise RuntimeError("no repr")


def _cyclic() -> list[Any]:
    a: list[Any] = []
    a.append(a)
    return a


_non_json = st.sampled_from(
    [object(), _Opaque(), {1, 2}, b"\xff\xfe", float("nan"), _cyclic(), {"cart": object()}, lambda: 1]
)


def _assert_shape(result: Any) -> None:
    assert result.decision in {"ALLOW", "BLOCK", "ASK_HUMAN"}
    assert result.reason_codes
    assert set(result.reason_codes) <= _CODES
    assert len(result.explanation) <= 400
    assert result.explanation.endswith(NOTICE)
    if result.decision == "ALLOW":
        assert result.reason_codes == ["CLEAN"]
        assert result.spans == []


# Feature: paygate, Property 2: Result shape invariant
# **Validates: Requirements 2.1, 2.2, 2.4, 6.3, 12.2**
@_SETTINGS
@given(raw=st.one_of(_json_value, _non_json))
def test_result_shape_arbitrary_input(gate_log: DecisionLog, raw: Any) -> None:
    _assert_shape(gate_purchase(raw, log=gate_log))


# Feature: paygate, Property 2: Result shape invariant
# **Validates: Requirements 2.1, 2.2, 2.4, 6.3, 12.2**
@_SETTINGS
@given(req=signed_request(), replay=st.booleans())
def test_result_shape_signed_request(gate_log: DecisionLog, req: Any, replay: bool) -> None:
    _assert_shape(gate_purchase(req, replay=replay, log=gate_log))


# Feature: paygate, Property 3: Invalid requests are rejected with paths
# **Validates: Requirements 1.3, 1.4, 1.5, 5.6**
@_SETTINGS
@given(raw=mutated_request())
def test_mutated_requests_rejected_with_paths(gate_log: DecisionLog, raw: dict[str, Any]) -> None:
    result = gate_purchase(raw, log=gate_log)
    assert result.decision == "ASK_HUMAN"
    assert result.reason_codes == ["INPUT_MALFORMED"]
    oversize = len(raw.get("content") or []) == 1 and len(str(raw["content"][0].get("text", ""))) > 1_000_000
    if not oversize:
        assert result.errors
        assert all(e.path.startswith("$") for e in result.errors)


# Feature: paygate, Property 3: Invalid requests are rejected with paths
# **Validates: Requirements 1.3, 1.4, 1.5, 5.6**
@_SETTINGS
@given(raw=_json_value.filter(lambda v: not isinstance(v, dict)))
def test_non_object_json_rejected_with_paths(gate_log: DecisionLog, raw: Any) -> None:
    result = gate_purchase(raw, log=gate_log)
    assert result.decision == "ASK_HUMAN"
    assert result.reason_codes == ["INPUT_MALFORMED"]
    assert result.errors
    assert result.errors[0].path == "$"
