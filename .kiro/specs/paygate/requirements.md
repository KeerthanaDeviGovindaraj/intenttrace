# Requirements Document

## Introduction

IntentTrace investigates agent purchases after the fact. PayGate moves the same checks to the moment before payment. An AI shopping agent calls PayGate with a proposed purchase, and PayGate returns `ALLOW`, `BLOCK`, or `ASK_HUMAN` before any money moves.

PayGate is a thin gate over existing IntentTrace modules. It reuses `checks/integrity.py` (Ed25519 signatures and hash chain), `checks/scope.py` (cart versus signed constraints), `forensics/detect.py` (rules R1-R5 and the optional LLM classifier), `forensics/deviation.py` (best-match ranking), `forensics/replay.py` (counterfactual replay), `evidence.py` (evidence packet writer), `crypto.py`, `store.py`, `api.py`, `mcp_server.py`, `bench.py`, the `sim/` generator, and the dashboard under `web/`. PayGate decides using deterministic rules only. It needs no LLM API key. The LLM path in `detect.py` and `influence.py` stays optional and is used only when a provider is configured.

The data model is AP2-style (as defined in the IntentTrace MVP spec), not AP2-compliant. All data is synthetic. PayGate output is a technical signal, not legal advice.

**MVP scope:** one Python function, one REST endpoint, one MCP tool, a decision log with signed hash-chained records, a Decisions view in the dashboard, and a benchmark section. Estimated effort is one to two days.

## Glossary

- **PayGate**: the pre-purchase checkpoint feature specified in this document.
- **Gate_Request**: the input to PayGate, made of one Intent Mandate, one proposed Cart Mandate, a list of Untrusted_Content_Items, and optional settings.
- **Intent_Mandate**: the user-signed constraints record, as `IntentMandate` in `models.py`.
- **Proposed_Cart**: the Cart Mandate the agent intends to pay for, as `CartMandate` in `models.py`. No Payment Mandate exists yet.
- **Untrusted_Content_Item**: one piece of text the agent read that did not come from the user, with a source (`merchant`, `review`, `qa`, `hidden`, `external_agent`) and an optional `product_id`.
- **Decision**: one of `ALLOW`, `BLOCK`, `ASK_HUMAN`.
- **Reason_Code**: a stable machine-readable string explaining part of a Decision (for example `INTEGRITY_SIGNATURE_INVALID`).
- **Gate_Result**: the output of PayGate: Decision, Reason_Codes, explanation, highlighted spans, and the decision record ID.
- **Highlighted_Span**: a character range inside one Untrusted_Content_Item that triggered a detection rule, reusing `Span` from `models.py`.
- **Decision_Record**: the persisted, signed, hash-chained log entry for one Decision.
- **Gate_Key**: the Ed25519 key pair PayGate uses to sign Decision_Records.
- **Decision_Log**: the ordered SQLite table of Decision_Records.
- **Attack_Case**: a benchmark case whose ground-truth label is `MANIPULATED`, `OUT_OF_SCOPE`, or `INTEGRITY_FAILURE`, other than the Payment_Only_Cases excluded under Requirement 11 criterion 7.
- **Payment_Only_Case**: a benchmark case labeled `INTEGRITY_FAILURE` with cause `amount_altered` or `cart_hash_altered`. These alter only the Payment Mandate, which does not exist before payment.
- **Legitimate_Case**: a benchmark case whose ground-truth label is `LEGITIMATE`.
- **Pipeline_Test**: a benchmark run that uses the `fake` provider or scripted agents, so its numbers test the pipeline and do not measure real-world accuracy.

## Requirements

### Requirement 1: Gate request input

**User Story:** As an agent developer, I want to submit a proposed purchase with its mandate and the content the agent read, so that PayGate can judge the purchase before payment.

#### Acceptance Criteria

1. THE PayGate SHALL accept a Gate_Request containing an Intent_Mandate, a Proposed_Cart, and a list of zero or more Untrusted_Content_Items.
2. THE PayGate SHALL accept an optional `AgentConfig` and optional `ListingSnapshot` list in the Gate_Request to enable best-match ranking and counterfactual replay.
3. THE PayGate SHALL validate the Gate_Request using Pydantic v2 models that forbid extra fields.
4. IF the Gate_Request fails validation, THEN THE PayGate SHALL return a Gate_Result with Decision `ASK_HUMAN`, Reason_Code `INPUT_MALFORMED`, and the JSON path of every validation error.
5. IF a string field in the Gate_Request contains a Luhn-valid 13 to 19 digit number, THEN THE PayGate SHALL treat the request as malformed under criterion 4.

### Requirement 2: Decision output

**User Story:** As an agent developer, I want a clear decision with reasons, so that my agent can act on the result and a human can understand it.

#### Acceptance Criteria

1. THE PayGate SHALL return a Gate_Result containing exactly one Decision, a non-empty list of Reason_Codes, an explanation of at most 400 characters, a list of Highlighted_Spans, and a decision record ID.
2. THE PayGate SHALL draw Reason_Codes from a fixed documented set that includes `INTEGRITY_SIGNATURE_INVALID`, `INTEGRITY_HASH_CHAIN_BROKEN`, `SCOPE_VIOLATION`, `INJECTION_DETECTED`, `BEST_MATCH_DEVIATION`, `REPLAY_CHANGED_CHOICE`, `INPUT_MALFORMED`, `CHECK_FAILED`, and `CLEAN`.
3. THE PayGate SHALL express each Highlighted_Span as a content item ID, a start offset, an end offset, and the rule ID that fired.
4. WHEN a Decision is `ALLOW`, THE PayGate SHALL return the Reason_Code `CLEAN` and an empty list of Highlighted_Spans.
5. THE PayGate SHALL generate the explanation from templates keyed by Reason_Code, without calling an LLM.

### Requirement 3: Decision rules

**User Story:** As a security reviewer, I want ordered, deterministic decision rules, so that the outcome for a given input is predictable and testable.

#### Acceptance Criteria

1. WHEN the integrity check reports any signature failure or hash-reference mismatch, THE PayGate SHALL return Decision `BLOCK` with the matching `INTEGRITY_*` Reason_Code.
2. WHEN the scope check reports any violated constraint, THE PayGate SHALL return Decision `BLOCK` with Reason_Code `SCOPE_VIOLATION` and one entry per violated constraint.
3. WHEN injection detection flags at least one span AND counterfactual replay reports that the choice changes when the flagged spans are removed, THE PayGate SHALL return Decision `BLOCK` with Reason_Codes `INJECTION_DETECTED` and `REPLAY_CHANGED_CHOICE`.
4. WHEN injection detection flags at least one span AND the chosen item differs from the top best-match candidate, THE PayGate SHALL return Decision `BLOCK` with Reason_Codes `INJECTION_DETECTED` and `BEST_MATCH_DEVIATION`.
5. WHEN injection detection flags at least one span AND neither replay changes the choice nor best-match deviation is found, THE PayGate SHALL return Decision `ASK_HUMAN` with Reason_Code `INJECTION_DETECTED`.
6. WHEN no span is flagged AND the chosen item differs from the top best-match candidate, THE PayGate SHALL return Decision `ASK_HUMAN` with Reason_Code `BEST_MATCH_DEVIATION`.
7. WHEN integrity passes, scope passes, no span is flagged, and no best-match deviation is found, THE PayGate SHALL return Decision `ALLOW` with Reason_Code `CLEAN`.
8. THE PayGate SHALL evaluate the rules in the order of criteria 1 to 7 and SHALL stop at the first rule that yields `BLOCK`.
9. WHEN the Gate_Request omits listings or `AgentConfig`, THE PayGate SHALL skip best-match ranking or replay respectively, and SHALL list the skipped check in the Gate_Result.
10. THE PayGate SHALL return the same Gate_Result for the same Gate_Request when no LLM provider is configured, excluding the decision record ID and timestamps.

### Requirement 4: Reuse of IntentTrace modules

**User Story:** As the maintainer, I want PayGate built on the existing modules, so that the gate and the post-purchase investigator never disagree on the same facts.

#### Acceptance Criteria

1. THE PayGate SHALL call `check_integrity` from `checks/integrity.py`, `check_scope` from `checks/scope.py`, `detect` from `forensics/detect.py`, `check_deviation` from `forensics/deviation.py`, and `replay` from `forensics/replay.py` rather than re-implementing their logic.
2. THE PayGate SHALL build its Highlighted_Spans from the `Span` objects returned by `detect`.
3. THE PayGate SHALL reuse the evidence packet writer in `evidence.py` to render a Markdown evidence packet for any stored Decision_Record.
4. WHEN no LLM provider is configured, THE PayGate SHALL call `detect` with the rule-only path and SHALL make zero network calls.
5. WHERE `INTENTTRACE_LLM_PROVIDER` selects a real provider, THE PayGate SHALL pass that provider to `detect` so the LLM classifier can add spans.
6. THE PayGate SHALL adapt a Gate_Request into the input shapes the reused modules expect without modifying the behavior of those modules for existing IntentTrace callers.

### Requirement 5: Fail-safe behavior

**User Story:** As an agent developer, I want PayGate to refuse to approve a purchase when it cannot be sure, so that a failure never lets money move.

#### Acceptance Criteria

1. IF any reused check raises an unexpected exception, THEN THE PayGate SHALL return Decision `BLOCK` or `ASK_HUMAN` with Reason_Code `CHECK_FAILED` and the name of the failed check.
2. IF the integrity check cannot run because a required public key or signature is missing, THEN THE PayGate SHALL return Decision `BLOCK` with Reason_Code `INTEGRITY_SIGNATURE_INVALID`.
3. IF the optional LLM provider is unavailable, THEN THE PayGate SHALL continue with deterministic checks and SHALL record a `llm_unavailable` note in the Gate_Result.
4. IF the Decision_Log cannot be written, THEN THE PayGate SHALL return Decision `ASK_HUMAN` with Reason_Code `CHECK_FAILED` instead of the computed Decision.
5. THE PayGate SHALL return `ALLOW` only when integrity, scope, and detection have all run to completion and the rules in Requirement 3 criterion 7 are satisfied.
6. IF the Gate_Request exceeds 1 MB, THEN THE PayGate SHALL return Decision `ASK_HUMAN` with Reason_Code `INPUT_MALFORMED`.

### Requirement 6: Python function interface

**User Story:** As an agent developer, I want to call PayGate as a function, so that I can embed it in my agent without running a server.

#### Acceptance Criteria

1. THE PayGate SHALL expose a function `gate_purchase(request, provider=None, replay=True)` in a module `intenttrace/paygate.py` that returns a Gate_Result.
2. THE `gate_purchase` function SHALL accept either a Gate_Request model or a plain dictionary.
3. THE `gate_purchase` function SHALL return a Gate_Result for every input and SHALL NOT raise an exception to the caller.
4. WHEN `gate_purchase` is called, THE PayGate SHALL write one Decision_Record before returning.
5. WHERE the caller sets `replay=False`, THE PayGate SHALL skip counterfactual replay and SHALL list replay as skipped.

### Requirement 7: HTTP endpoint

**User Story:** As an agent developer, I want an HTTP endpoint, so that agents in any language can call PayGate.

#### Acceptance Criteria

1. THE PayGate SHALL extend the FastAPI app in `api.py` with `POST /api/paygate/check`.
2. WHEN a request body is valid JSON, THE PayGate SHALL return HTTP 200 with the Gate_Result as JSON for every Decision, including `BLOCK` and `ASK_HUMAN`.
3. IF the request body is not valid JSON, THEN THE PayGate SHALL return HTTP 422 with Decision `ASK_HUMAN` and Reason_Code `INPUT_MALFORMED` in the body.
4. THE PayGate SHALL extend `api.py` with `GET /api/paygate/decisions` that returns Decision_Records newest first and accepts an optional `decision` query parameter with value `ALLOW`, `BLOCK`, or `ASK_HUMAN`.
5. THE PayGate SHALL extend `api.py` with `GET /api/paygate/decisions/{id}/evidence.md` that returns the Markdown evidence packet for one Decision_Record.
6. IF a Decision_Record ID does not exist, THEN THE PayGate SHALL return HTTP 404.
7. THE PayGate SHALL keep the existing binding to `127.0.0.1` and the existing CORS settings.

### Requirement 8: MCP tool

**User Story:** As a user of an MCP-capable AI agent, I want a PayGate tool, so that the agent can check a purchase before paying.

#### Acceptance Criteria

1. THE PayGate SHALL register a tool `check_purchase` in `mcp_server.py` through `create_server`.
2. THE `check_purchase` tool SHALL accept the Gate_Request as a JSON string and return the Gate_Result as a JSON-serializable dictionary.
3. IF the JSON string cannot be parsed, THEN THE `check_purchase` tool SHALL return a Gate_Result with Decision `ASK_HUMAN` and Reason_Code `INPUT_MALFORMED` rather than raising an exception.
4. THE `check_purchase` tool SHALL write the same Decision_Record as the Python function would for the same input.
5. THE PayGate SHALL keep the existing MCP tools `investigate_purchase`, `get_case`, and `list_cases` unchanged.

### Requirement 9: Signed, hash-chained decision log

**User Story:** As an auditor, I want every decision recorded in a tamper-evident log, so that I can show later what PayGate decided and why.

#### Acceptance Criteria

1. THE PayGate SHALL write one Decision_Record for every Gate_Result, including `ALLOW`, `BLOCK`, and `ASK_HUMAN`.
2. THE Decision_Record SHALL contain a record ID, a UTC timestamp, the Decision, the Reason_Codes, the explanation, the Highlighted_Spans, a SHA-256 hash of the canonical Gate_Request, the hash of the previous Decision_Record, and an Ed25519 signature.
3. THE PayGate SHALL sign each Decision_Record with the Gate_Key using the canonical JSON encoding from `crypto.py`.
4. THE PayGate SHALL compute each record hash over the canonical record including its signature, and SHALL store it as the `previous_hash` of the next record.
5. THE PayGate SHALL use a fixed all-zero hash as the `previous_hash` of the first record.
6. THE PayGate SHALL store Decision_Records in a new `decisions` table in the same SQLite database as `store.py`.
7. THE PayGate SHALL provide a function `verify_decision_log()` that returns the ID of the first record whose signature or chain link is invalid, or `None` when the whole log is valid.
8. WHEN two Decision_Records are written concurrently, THE PayGate SHALL still produce a single linear chain without duplicated `previous_hash` values.
9. WHERE the environment variable `PAYGATE_KEY_FILE` is set, THE PayGate SHALL load the Gate_Key from that path.
10. WHERE `PAYGATE_KEY_FILE` is not set, THE PayGate SHALL generate a Gate_Key on first use, persist the Gate_Key beside the database, and record the public key in the Decision_Log.
11. THE PayGate SHALL store a hash of the Gate_Request and the Highlighted_Spans in the record, and SHALL NOT store the full untrusted content in the record.

### Requirement 10: Dashboard Decisions view

**User Story:** As a reviewer, I want to see PayGate decisions in the dashboard, so that I can audit what the gate allowed and blocked.

#### Acceptance Criteria

1. THE PayGate SHALL add a `Decisions` page to the dashboard in `web/src/pages/` reachable from the main navigation.
2. THE Decisions page SHALL list Decision_Records newest first with the timestamp, Decision badge, Reason_Codes, and explanation.
3. THE Decisions page SHALL provide filter controls for `ALL`, `ALLOW`, `BLOCK`, and `ASK_HUMAN` that call `GET /api/paygate/decisions` with the matching `decision` parameter.
4. WHEN the user opens a Decision_Record, THE Decisions page SHALL show its Highlighted_Spans and a link to download its Markdown evidence packet.
5. WHEN the log is empty, THE Decisions page SHALL display an empty-state message.
6. THE Decisions page SHALL show a visible chain status derived from `verify_decision_log()`.
7. THE Decisions page SHALL support the existing light and dark themes and remain usable at 390 px width.

### Requirement 11: Benchmark measurement

**User Story:** As the maintainer, I want PayGate measured on the existing benchmark, so that every claim is backed by numbers.

#### Acceptance Criteria

1. THE PayGate SHALL provide a benchmark mode in `bench.py` that converts each generated case from `benchmark/cases/` into a Gate_Request and runs `gate_purchase` on the converted request.
2. THE benchmark mode SHALL report the block rate on Attack_Cases, defined as the share of Attack_Cases with Decision `BLOCK`.
3. THE benchmark mode SHALL report the false-block rate on Legitimate_Cases, defined as the share of Legitimate_Cases with Decision `BLOCK`.
4. THE benchmark mode SHALL report the ASK_HUMAN rate separately for Attack_Cases and for Legitimate_Cases.
5. THE benchmark mode SHALL report the block rate for each attack type and for each Attack_Case label.
6. THE benchmark mode SHALL report p50 and p95 latency per decision in milliseconds, excluding LLM latency when no provider is configured.
7. THE benchmark mode SHALL exclude from the block rate, the false-block rate, and the ASK_HUMAN rate every case labeled `MERCHANT_MISREPRESENTATION` and every case labeled `INTEGRITY_FAILURE` whose cause is `amount_altered` or `cart_hash_altered`, SHALL report the count of excluded cases per exclusion group, and SHALL state in its output the reason for each group: the first group appears only after purchase, and the second group alters only the Payment Mandate, which does not exist before payment.
8. THE benchmark mode SHALL write its results to a PayGate section in `benchmark/RESULTS.md` and to `benchmark/results.json`, without removing the existing IntentTrace results.
9. WHILE the benchmark uses the `fake` provider or scripted agents, THE benchmark mode SHALL label its output "Pipeline test on synthetic data. Not a measure of real-world accuracy."
10. WHEN run with `--min-block-rate <x>` or `--max-false-block-rate <y>`, THE benchmark mode SHALL exit with a non-zero status if a threshold is missed.
11. THE benchmark mode SHALL write benchmark Decision_Records to a temporary database and SHALL NOT write them to the user's Decision_Log.

### Requirement 12: Honest limitations

**User Story:** As a reader of the project, I want clear limits stated, so that I do not mistake PayGate for a production fraud control.

#### Acceptance Criteria

1. THE README SHALL contain a PayGate section that states the data is synthetic, the detection rules are English-only, the data model is AP2-style and not AP2-compliant, and the output is not legal advice.
2. THE Gate_Result explanation and the Markdown evidence packet SHALL include the notice "Technical signal on synthetic data. Not legal advice."
3. THE PayGate section in `benchmark/RESULTS.md` SHALL state the provider, the seed, the number of cases, and the date.
4. THE README SHALL state that rule-based detection can be bypassed by paraphrased attacks and that a passing `ALLOW` is not a guarantee of safety.
5. THE README SHALL list the out-of-scope items from this document.

### Requirement 13: Quality and CI

**User Story:** As the maintainer, I want PayGate covered by tests that run offline, so that regressions are caught on every push.

#### Acceptance Criteria

1. THE PayGate SHALL have unit tests for each decision rule in Requirement 3, each fail-safe condition in Requirement 5, and decision log verification in Requirement 9, and the tests SHALL need no network and no API keys.
2. THE PayGate SHALL have API tests using the FastAPI `TestClient` and a direct test of the `check_purchase` MCP tool function.
3. THE PayGate SHALL have a test that tampers with one stored Decision_Record and confirms `verify_decision_log()` returns that record ID.
4. THE PayGate SHALL have a test that the committed sample cases in `benchmark/sample/` yield the expected Decisions.
5. WHEN CI runs, THE PayGate benchmark mode SHALL run on the fake provider against the generated cases and SHALL enforce thresholds set in the CI workflow.
6. THE PayGate code SHALL pass the existing `ruff` configuration.

## Out of Scope

- Real payment execution, payment rails, card handling, or merchant integrations.
- Official AP2 or ACP SDK interoperability or compliance.
- Automatic human approval workflows (notifications, approve and deny buttons). `ASK_HUMAN` only returns the decision.
- Authentication, user accounts, rate limiting, or multi-tenant separation for the HTTP endpoint.
- Non-English detection rules and multimodal content (images, audio, PDFs).
- Detection of post-purchase merchant misrepresentation, since delivered-item data does not exist before payment.
- Training or tuning models, or a required LLM path; the LLM provider remains optional.
- Key management beyond a local key file (no HSM, rotation, or revocation).
- Legal, liability, or chargeback determinations.
- Real-world accuracy claims; all results are on synthetic data.
