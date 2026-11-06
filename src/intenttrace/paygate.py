"""PayGate: pre-purchase gate over the existing IntentTrace checks.

This module holds the request/result models and the input validation helper.
Synthetic data only. Technical signal on synthetic data. Not legal advice.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

from .checks.integrity import check_integrity
from .checks.scope import check_scope
from .crypto import canonical, mandate_hash
from .forensics.detect import detect
from .forensics.deviation import check_deviation
from .forensics.replay import original_choice
from .forensics.replay import replay as run_replay
from .llm.base import LLMProvider
from .llm.factory import make_provider
from .models import (
    AgentConfig,
    CartMandate,
    CaseFile,
    IntentMandate,
    ListingSnapshot,
    PaymentMandate,
    TraceStep,
    _Model,
)

MAX_REQUEST_BYTES = 1_000_000  # 1 MB

Decision = Literal["ALLOW", "BLOCK", "ASK_HUMAN"]
ReasonCode = Literal[
    "INTEGRITY_SIGNATURE_INVALID",
    "INTEGRITY_HASH_CHAIN_BROKEN",
    "INTEGRITY_TOTAL_MISMATCH",
    "INTEGRITY_SIGNER_VIOLATION",
    "SCOPE_VIOLATION",
    "INJECTION_DETECTED",
    "BEST_MATCH_DEVIATION",
    "REPLAY_CHANGED_CHOICE",
    "INPUT_MALFORMED",
    "CHECK_FAILED",
    "CLEAN",
]


class ContentItem(_Model):
    """One piece of untrusted text the agent read."""

    item_id: str | None = None  # defaults to "c{index}" in GateRequest
    source: Literal["merchant", "review", "qa", "hidden", "external_agent"]
    text: str
    product_id: str | None = None


class GateRequest(_Model):
    public_keys: dict[str, str]
    intent: IntentMandate
    cart: CartMandate
    content: list[ContentItem] = Field(default_factory=list)
    listings: list[ListingSnapshot] | None = None
    agent_config: AgentConfig | None = None

    @field_validator("cart")
    @classmethod
    def _cart_has_items(cls, cart: CartMandate) -> CartMandate:
        if not cart.items:
            raise ValueError("cart must contain at least one item")
        return cart

    @field_validator("content")
    @classmethod
    def _assign_unique_item_ids(cls, items: list[ContentItem]) -> list[ContentItem]:
        filled = [
            it if it.item_id is not None else it.model_copy(update={"item_id": f"c{i}"})
            for i, it in enumerate(items)
        ]
        ids = [it.item_id for it in filled]
        if len(set(ids)) != len(ids):
            raise ValueError("content item_id values must be unique")
        return filled


class HighlightedSpan(BaseModel):
    item_id: str
    start: int
    end: int
    rule_id: str


class ErrorItem(BaseModel):
    path: str  # JSON path such as "$.cart.items[0].quantity"
    msg: str


class GateResult(BaseModel):
    decision: Decision
    reason_codes: list[ReasonCode] = Field(min_length=1)
    explanation: str = Field(max_length=400)
    spans: list[HighlightedSpan] = Field(default_factory=list)
    skipped_checks: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    errors: list[ErrorItem] = Field(default_factory=list)
    record_id: str | None = None


@dataclass(frozen=True)
class Facts:
    """Inputs to the pure decision rule."""

    integrity_codes: tuple[ReasonCode, ...] = ()
    scope_violations: int = 0
    flagged_spans: int = 0
    replay: Literal["changed", "unchanged", "unavailable"] = "unavailable"
    deviation: Literal["deviates", "matches", "unavailable"] = "unavailable"


@dataclass(frozen=True)
class Outcome:
    decision: Decision
    reason_codes: tuple[ReasonCode, ...]


_INTEGRITY_CODE_BY_KIND: dict[str, ReasonCode] = {
    "signature_invalid": "INTEGRITY_SIGNATURE_INVALID",
    "hash_mismatch": "INTEGRITY_HASH_CHAIN_BROKEN",
    "total_mismatch": "INTEGRITY_TOTAL_MISMATCH",
    "signer_violation": "INTEGRITY_SIGNER_VIOLATION",
}


def integrity_code_for_kind(kind: str) -> ReasonCode | None:
    """Map an integrity Finding.kind to a ReasonCode. None means the finding is dropped."""
    return _INTEGRITY_CODE_BY_KIND.get(kind)


def decide_from_facts(facts: Facts) -> Outcome:
    """Pure ordered rule table. First match wins."""
    if facts.integrity_codes:
        return Outcome("BLOCK", tuple(dict.fromkeys(facts.integrity_codes)))
    if facts.scope_violations > 0:
        return Outcome("BLOCK", ("SCOPE_VIOLATION",))
    if facts.flagged_spans > 0:
        if facts.replay == "changed":
            return Outcome("BLOCK", ("INJECTION_DETECTED", "REPLAY_CHANGED_CHOICE"))
        if facts.deviation == "deviates":
            return Outcome("BLOCK", ("INJECTION_DETECTED", "BEST_MATCH_DEVIATION"))
        return Outcome("ASK_HUMAN", ("INJECTION_DETECTED",))
    if facts.deviation == "deviates":
        return Outcome("ASK_HUMAN", ("BEST_MATCH_DEVIATION",))
    return Outcome("ALLOW", ("CLEAN",))


NOTICE = "Technical signal on synthetic data. Not legal advice."
_TEMPLATE_LIMIT = 340

# Fixed templates. Only counts and fixed check names may be interpolated.
EXPLANATION_TEMPLATES: dict[ReasonCode, str] = {
    "INTEGRITY_SIGNATURE_INVALID": "A mandate signature is missing or does not verify.",
    "INTEGRITY_HASH_CHAIN_BROKEN": "The cart does not match the intent it claims to extend.",
    "INTEGRITY_TOTAL_MISMATCH": "The cart total does not equal the sum of its items.",
    "INTEGRITY_SIGNER_VIOLATION": "A human must be present but the cart is not user-signed.",
    "SCOPE_VIOLATION": "The cart breaks {count} signed constraint(s).",
    "INJECTION_DETECTED": "{count} suspicious span(s) found in untrusted content.",
    "BEST_MATCH_DEVIATION": "The chosen item is not the top match for the intent.",
    "REPLAY_CHANGED_CHOICE": "Removing the flagged text changes the agent's choice.",
    "INPUT_MALFORMED": "The request is invalid or too large.",
    "CHECK_FAILED": "A check could not complete: {check}.",
    "CLEAN": "Integrity, scope and detection checks found no issue.",
}


def build_explanation(
    reason_codes: tuple[ReasonCode, ...] | list[ReasonCode],
    count: int = 0,
    check: str = "unknown",
) -> str:
    """Explanation from the primary code's template plus the fixed notice. At most 400 chars."""
    template = EXPLANATION_TEMPLATES[reason_codes[0]]
    body = template.format(count=count, check=check)[:_TEMPLATE_LIMIT]
    return f"{body} {NOTICE}"


CASE_ID = "paygate-request"
PROVIDER_ENV = "INTENTTRACE_LLM_PROVIDER"

# Request content source -> trace step source (the trace allows a different set of sources).
_TRACE_SOURCE: dict[str, Literal["merchant", "review", "external_agent"]] = {
    "merchant": "merchant",
    "review": "review",
    "qa": "review",
    "hidden": "external_agent",
    "external_agent": "external_agent",
}


def request_to_case(req: GateRequest) -> CaseFile:
    """Adapt a GateRequest into a CaseFile for the reused checks.

    The payment is an unsigned placeholder, so only its signature can fail integrity.
    Observe step IDs equal content item IDs, so returned spans need no translation.
    """
    cart = req.cart
    placeholder = PaymentMandate(
        mandate_id="paygate-placeholder",
        cart_mandate_hash=mandate_hash(cart),
        amount_cents=cart.total_cents,
        payment_method_token="paygate-placeholder",
        agent_involved=True,
        created_at=cart.created_at,
        signer="agent",
        signature="",
    )
    ts = req.intent.created_at
    trace = [
        TraceStep(
            step_id="paygate-instruction",
            kind="instruction",
            source="user",
            content=req.intent.natural_language,
            timestamp=ts,
        )
    ]
    for item in req.content:
        trace.append(
            TraceStep(
                step_id=str(item.item_id),
                kind="observe",
                source=_TRACE_SOURCE[item.source],
                content=item.text,
                product_id=item.product_id,
                timestamp=ts,
            )
        )
    trace.append(
        TraceStep(
            step_id="paygate-decide",
            kind="decide",
            source="agent",
            content="proposed purchase",
            product_id=cart.items[0].product_id,
            timestamp=ts,
        )
    )
    return CaseFile(
        case_id=CASE_ID,
        public_keys=req.public_keys,
        intent=req.intent,
        cart=cart,
        payment=placeholder,
        trace=trace,
        listings_at_purchase=list(req.listings or []),
        listing_after=None,
        delivered=None,
        agent_config=req.agent_config,
    )


def provider_from_env() -> tuple[LLMProvider | None, list[str]]:
    """Select an LLM provider from INTENTTRACE_LLM_PROVIDER. Unset, empty or 'none' means rules only."""
    name = os.environ.get(PROVIDER_ENV, "").strip()
    if not name or name.lower() == "none":
        return None, []
    try:
        return make_provider(name), []
    except ValueError:
        return None, ["llm_unavailable"]


class RequestError(Exception):
    """Raised by validate_request. Carries JSON-path errors and never echoes input values."""

    def __init__(self, errors: list[ErrorItem], oversize: bool = False) -> None:
        super().__init__("; ".join(f"{e.path}: {e.msg}" for e in errors))
        self.errors = errors
        self.oversize = oversize


# Fixed messages by Pydantic error type; the input value is never included.
_MSG_BY_TYPE = {
    "missing": "field is required",
    "extra_forbidden": "unknown field",
    "string_type": "must be a string",
    "int_type": "must be an integer",
    "bool_type": "must be a boolean",
    "list_type": "must be a list",
    "dict_type": "must be an object",
    "literal_error": "value not allowed",
    "model_type": "must be an object",
}


def _json_path(loc: tuple[Any, ...]) -> str:
    path = "$"
    for part in loc:
        path += f"[{part}]" if isinstance(part, int) else f".{part}"
    return path


def _error_items(exc: ValidationError) -> list[ErrorItem]:
    items: list[ErrorItem] = []
    for err in exc.errors(include_input=False, include_url=False):
        etype = err["type"]
        if etype == "value_error":
            # Messages come from our own validators and never contain input values.
            msg = err["msg"].removeprefix("Value error, ")
        else:
            msg = _MSG_BY_TYPE.get(etype, "invalid value")
        items.append(ErrorItem(path=_json_path(err["loc"]), msg=msg))
    return items


def validate_request(raw: Any) -> GateRequest:
    """Validate a raw request (model, dict, JSON str/bytes). Raise RequestError on failure."""
    if isinstance(raw, GateRequest):
        raw = raw.model_dump()
    try:
        if isinstance(raw, bytes | str):
            size = len(raw.encode("utf-8")) if isinstance(raw, str) else len(raw)
            if size > MAX_REQUEST_BYTES:
                raise RequestError([ErrorItem(path="$", msg="request exceeds 1 MB")], oversize=True)
            raw = json.loads(raw)
        else:
            size = len(json.dumps(raw, default=str).encode("utf-8"))
            if size > MAX_REQUEST_BYTES:
                raise RequestError([ErrorItem(path="$", msg="request exceeds 1 MB")], oversize=True)
    except RequestError:
        raise
    except (ValueError, TypeError, RecursionError):
        raise RequestError([ErrorItem(path="$", msg="request is not valid JSON")]) from None
    if not isinstance(raw, dict):
        raise RequestError([ErrorItem(path="$", msg="request must be a JSON object")])
    try:
        return GateRequest.model_validate(raw)
    except ValidationError as exc:
        raise RequestError(_error_items(exc)) from None


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


class _CheckFailed(Exception):
    """Internal: a named check raised. Carries only the fixed check name."""

    def __init__(self, check: str) -> None:
        super().__init__(check)
        self.check = check


def _run_check(name: str, fn: Any, *args: Any) -> Any:
    try:
        return fn(*args)
    except Exception:
        raise _CheckFailed(name) from None


def _request_hash(raw: Any, req: GateRequest | None) -> str:
    try:
        if req is not None:
            return hashlib.sha256(canonical(req.model_dump())).hexdigest()
        data = json.dumps(raw, default=str, sort_keys=True).encode("utf-8", "replace")
    except Exception:
        data = b"unhashable"
    return hashlib.sha256(data).hexdigest()


def _failed_result(check: str, record_id: str | None = None) -> GateResult:
    """CHECK_FAILED result built from constants and a fixed check name only."""
    codes: list[ReasonCode] = ["CHECK_FAILED"]
    return GateResult(
        decision="ASK_HUMAN",
        reason_codes=codes,
        explanation=build_explanation(codes, check=check),
        record_id=record_id,
    )


def gate_purchase(
    request: GateRequest | dict[str, Any],
    provider: LLMProvider | None = None,
    replay: bool = True,
    *,
    log: Any = None,
) -> GateResult:
    """Decide ALLOW, BLOCK or ASK_HUMAN for a proposed purchase. Never raises.

    ``provider=None`` runs rules only and makes no network calls. One record is appended to
    ``log`` (a default ``DecisionLog()`` when None) per call.
    """
    try:
        return _gate(request, provider, replay, log)
    except Exception:
        return _failed_result("gate")


def _gate(request: Any, provider: LLMProvider | None, replay: bool, log: Any) -> GateResult:
    from .paygate_log import DecisionLog, RecordInput  # lazy: paygate_log imports this module

    own_log = False
    try:
        if log is None:
            log = DecisionLog()
            own_log = True
    except Exception:
        return _failed_result("log")
    try:
        req: GateRequest | None = None
        errors: list[ErrorItem] = []
        skipped: list[str] = []
        notes: list[str] = []
        spans: list[HighlightedSpan] = []
        count = 0
        check = "unknown"
        try:
            req = validate_request(request)
            decision, codes_t, count = _evaluate(req, provider, replay, skipped, notes, spans)
        except RequestError as exc:
            errors = exc.errors
            decision, codes_t = "ASK_HUMAN", ("INPUT_MALFORMED",)
        except _CheckFailed as exc:
            decision, codes_t, check = "ASK_HUMAN", ("CHECK_FAILED",), exc.check
            spans, skipped, notes = [], [], []
        explanation = build_explanation(codes_t, count=count, check=check)
        try:
            record = log.append(
                RecordInput(
                    decision=decision,
                    reason_codes=list(codes_t),
                    explanation=explanation,
                    spans=spans,
                    skipped_checks=skipped,
                    request_hash=_request_hash(request, req),
                )
            )
        except Exception:
            return _failed_result("log")
        return GateResult(
            decision=decision,
            reason_codes=list(codes_t),
            explanation=explanation,
            spans=spans,
            skipped_checks=skipped,
            notes=notes,
            errors=errors,
            record_id=record.record_id,
        )
    finally:
        if own_log:
            try:
                log.close()
            except Exception:
                pass


def _evaluate(
    req: GateRequest,
    provider: LLMProvider | None,
    replay: bool,
    skipped: list[str],
    notes: list[str],
    spans_out: list[HighlightedSpan],
) -> tuple[Decision, tuple[ReasonCode, ...], int]:
    case = _run_check("adapter", request_to_case, req)

    integrity = _run_check("integrity", check_integrity, case)
    codes: list[ReasonCode] = []
    for f in integrity.failures:
        if (f.field or "").startswith("payment."):
            continue
        code = integrity_code_for_kind(f.kind)
        if code is not None:
            codes.append(code)
    outcome = decide_from_facts(Facts(integrity_codes=tuple(codes)))
    if codes:
        return outcome.decision, outcome.reason_codes, 0

    scope = _run_check("scope", check_scope, case)
    violations = len(scope.violations)
    if violations:
        outcome = decide_from_facts(Facts(scope_violations=violations))
        return outcome.decision, outcome.reason_codes, violations

    detection = _run_check("detect", detect, case, provider)
    if any(f.kind == "llm_unavailable" for f in detection.findings):
        notes.append("llm_unavailable")
    spans_out.extend(
        HighlightedSpan(
            item_id=s.step_id, start=s.start, end=s.end, rule_id=s.rule_id or s.method or "unknown"
        )
        for s in detection.spans
    )
    flagged = len(detection.spans)

    replay_state: Literal["changed", "unchanged", "unavailable"] = "unavailable"
    if not replay:
        skipped.append("replay: disabled")
    elif req.agent_config is None:
        skipped.append("replay: no agent_config")
    elif flagged:
        result = _run_check("replay", run_replay, case, detection.spans, True)
        replay_state = result.result
        if replay_state == "unavailable":
            skipped.append(f"replay: {result.reason or 'unavailable'}")

    deviation_state: Literal["deviates", "matches", "unavailable"] = "unavailable"
    if not req.listings:
        skipped.append("deviation: no listings")
    else:
        dev = _run_check(
            "deviation",
            check_deviation,
            req.intent.natural_language,
            req.intent.constraints,
            req.listings,
            original_choice(case),
        )
        if dev.eligible_count == 0:
            skipped.append("deviation: no eligible listing")
        else:
            deviation_state = "deviates" if dev.deviation else "matches"

    outcome = decide_from_facts(Facts(flagged_spans=flagged, replay=replay_state, deviation=deviation_state))
    return outcome.decision, outcome.reason_codes, flagged
