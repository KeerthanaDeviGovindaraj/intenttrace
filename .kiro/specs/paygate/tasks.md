# Implementation Plan: PayGate (MVP)

## Overview

PayGate is a pre-purchase gate over the existing IntentTrace checks. The plan builds it bottom-up: models and the pure rule function first, then the request adapter, then the signed decision log, then `gate_purchase` that joins them. After that come the interfaces (API, MCP), the benchmark and CLI, the dashboard page, and finally CI and README. Each step uses code from the previous steps, and the last tasks wire everything together. No existing check, forensics, or evidence module changes behavior.

Rules for every task: implement, write tests, run `ruff check . && ruff format . && pytest -q`, and only mark the task done when everything passes. All tests run offline with no API keys. Property tests use `hypothesis` with at least 100 examples and carry the comment tag `# Feature: paygate, Property N: <title>`. Commit after each top-level task with message `task N: <title>`.

## Tasks

- [x] 1. Project setup
  - [x] 1.1 Add `hypothesis` with a pinned version to the `dev` extra in `pyproject.toml`
    - _Requirements: 13.1_
  - [x] 1.2 Add the default PayGate key file pattern (`*.paygate.key`) to `.gitignore`
    - _Requirements: 9.10_

- [x] 2. Models and the pure decision rule
  - [x] 2.1 Create `src/intenttrace/paygate.py` with the Pydantic v2 models
    - `ContentItem`, `GateRequest`, `HighlightedSpan`, `ErrorItem`, `GateResult`, `Facts`, `Outcome`, and the `Decision` and `ReasonCode` literals, built on `models._Model` (extra fields forbidden)
    - Validators: at least one cart item, unique content `item_id` (default `c{index}`), Luhn-valid 13 to 19 digit numbers rejected in any string field
    - A `validate_request(raw)` helper that rejects payloads over 1 MB and maps Pydantic errors to JSON paths without echoing values
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.1, 2.2, 2.3, 5.6_
  - [x] 2.2 Implement `decide_from_facts(facts)` and the explanation templates in `paygate.py`
    - Ordered rule table rows 1 to 7, integrity finding to Reason_Code mapping, first match wins
    - Template dict keyed by Reason_Code, no LLM, no caller-supplied text, explanation capped at 400 characters and ending with "Technical signal on synthetic data. Not legal advice."
    - _Requirements: 2.2, 2.4, 2.5, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 5.5, 12.2_
  - [x]* 2.3 Write property test for the rule table
    - **Property 1: Rule table is total and ordered**
    - Use a flat `if` chain in the test as an independent oracle over generated `Facts`
    - **Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 5.5**

- [x] 3. Request adapter and provider selection
  - [x] 3.1 Implement `request_to_case(req)` and `provider_from_env()` in `paygate.py`
    - Build the placeholder `PaymentMandate`, the synthetic trace (instruction, one `observe` step per content item, one `decide` step), and the source mapping (`qa` to `review`, `hidden` to `external_agent`)
    - Step ID equals content item ID so spans need no translation
    - `provider_from_env()` returns `(None, [])` for unset, empty, or `none`; returns `(None, ["llm_unavailable"])` when `make_provider` raises
    - _Requirements: 1.2, 4.1, 4.2, 4.4, 4.5, 4.6, 5.3_
  - [x]* 3.2 Write unit tests for the adapter and provider selection
    - Source mapping table, placeholder payment yields only a `payment.signature` finding, empty cart and duplicate item IDs rejected, `provider_from_env` cases
    - _Requirements: 1.2, 4.6, 5.3_

- [x] 4. Signed, hash-chained decision log
  - [x] 4.1 Create `src/intenttrace/paygate_log.py` with `DecisionLog`, `DecisionRecord`, key handling, and `verify_decision_log`
    - Create the `decisions` and `decision_keys` tables with `CREATE TABLE IF NOT EXISTS` in `DecisionLog.__init__`; do not edit `Store.SCHEMA`
    - Key rules: `PAYGATE_KEY_FILE` loaded when set (never auto-created), otherwise `<db_path>.paygate.key` created with `O_CREAT|O_EXCL` and mode 0600; public key recorded in `decision_keys`
    - `append` runs `BEGIN IMMEDIATE`, signs with `crypto.sign`, hashes with `crypto.mandate_hash`, uses 64 zeros for the first `previous_hash`, and raises `LogWriteError` on failure
    - `list`, `get`, `close`, and `chain_status`; the record stores a request hash and span offsets, never content text
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 9.8, 9.9, 9.10, 9.11_
  - [x] 4.2 Add `decision_markdown(record)` to `paygate_log.py`
    - Build an `EvidencePacket` from the record and render it with `evidence.to_markdown`; append the "Decision record" section and the sentence that content text is not stored; include the legal notice
    - _Requirements: 4.3, 12.2_
  - [x]* 4.3 Write property test for chain verification and tamper location
    - **Property 9: Chain verifies, and any tamper is located**
    - Strategy `tampered_log()` appends N records to a temp log, then tampers one field of record k, or deletes a middle record
    - **Validates: Requirements 9.3, 9.4, 9.5, 9.7**
  - [x]* 4.4 Write unit tests for the log
    - Genesis hash, 8 concurrent writer threads produce one linear chain, key file mode 0600, explicit missing key file fails, `decision_keys` row present, tamper test returns the tampered record ID
    - _Requirements: 9.5, 9.8, 9.9, 9.10, 13.1, 13.3_

- [x] 5. Orchestration with `gate_purchase`
  - [x] 5.1 Implement `gate_purchase` in `paygate.py`
    - Validate, adapt, run integrity then scope (short-circuit on findings), then `detect`, `replay` (only when spans are flagged), and `check_deviation`; drop `payment.*` integrity failures; build `Facts`, call `decide_from_facts`, fill `skipped_checks` and `notes`, append one log record
    - Wrap the whole body in `try/except Exception`; per-check failures give `ASK_HUMAN / CHECK_FAILED` naming the check; a failed log write gives `ASK_HUMAN / CHECK_FAILED` with `record_id = None`; the fallback is built from constants only
    - Accept a model or dict, accept an injected `log`, make zero network calls when `provider=None`
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10, 4.1, 4.2, 4.4, 4.5, 5.1, 5.2, 5.3, 5.4, 5.5, 6.1, 6.2, 6.3, 6.4, 6.5, 9.1_
  - [x] 5.2 Create hypothesis strategies in `tests/strategies_paygate.py`
    - `facts()`, `signed_request()` (valid signed `GateRequest` varying price, quantity, content, listings, `agent_config`, with benign text mixed with R1 to R5 trigger phrases), `mutated_request()` (extra key, card number, removed field, oversize)
    - _Requirements: 13.1_
  - [x]* 5.3 Write property tests for result shape and input rejection
    - **Property 2: Result shape invariant**
    - **Validates: Requirements 2.1, 2.2, 2.4, 6.3, 12.2**
    - **Property 3: Invalid requests are rejected with paths**
    - **Validates: Requirements 1.3, 1.4, 1.5, 5.6**
  - [x]* 5.4 Write property tests for determinism, spans, and skipped checks
    - **Property 4: Determinism and input independence**
    - **Validates: Requirements 3.10, 6.2, 4.6**
    - **Property 5: Highlighted spans are well formed**
    - **Validates: Requirements 2.3, 4.2**
    - **Property 6: Skipped checks are reported**
    - **Validates: Requirements 1.2, 3.9, 6.5**
  - [x]* 5.5 Write property tests for fail-safe, record count, and leakage
    - **Property 7: Fail-safe on check failure or missing keys**
    - **Validates: Requirements 5.1, 5.2, 5.5**
    - **Property 8: One record per call, and records round trip**
    - **Validates: Requirements 6.4, 9.1, 9.2**
    - **Property 10: Untrusted text never leaks into stored or returned text**
    - **Validates: Requirements 2.5, 9.11**
  - [x]* 5.6 Write unit tests for the rule table and fail-safe paths
    - One case per rule row including replay `unavailable` falling through to rows 4 to 6, spies showing reused functions are called and later checks are skipped after a `BLOCK`, one monkeypatched exception per check, failing log, failing provider, `socket.socket` guard when `provider=None`
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 4.1, 4.4, 5.1, 5.3, 5.4, 13.1_

- [x] 6. Checkpoint - core gate
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. HTTP endpoints
  - [x] 7.1 Add the PayGate routes to `api.py`
    - `POST /api/paygate/check?replay=true` (200 for every Decision, 422 with an `INPUT_MALFORMED` body for non-JSON), `GET /api/paygate/decisions` (newest first, `decision` filter, `limit` 1 to 500, 422 on a bad filter), `GET /api/paygate/decisions/{id}/evidence.md` (404 if unknown), `GET /api/paygate/chain`
    - Use `provider_from_env()`; keep existing routes, `127.0.0.1` binding, and CORS unchanged
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 10.6_
  - [x]* 7.2 Write API tests with `TestClient`
    - 200 for ALLOW, BLOCK, ASK_HUMAN, and shape-invalid; 422 for non-JSON; newest-first list; filter; 404; evidence Markdown includes the notice; chain status; existing routes still pass
    - _Requirements: 7.2, 7.3, 7.4, 7.5, 7.6, 13.2_

- [x] 8. MCP tool
  - [x] 8.1 Add `check_purchase(request_json)` to `mcp_server.py` and register it in `create_server`
    - Parse the string, route unparseable input through `gate_purchase` so it yields `INPUT_MALFORMED`, return `model_dump(mode="json")`; leave the three existing tools unchanged
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5_
  - [x]* 8.2 Write tests for the MCP tool
    - Direct calls for valid and unparseable input, same record as the Python function, `create_server` lists four tools
    - _Requirements: 8.1, 8.3, 8.4, 8.5, 13.2_

- [x] 9. Benchmark mode and CLI
  - [x] 9.1 Add `case_to_request` and `run_paygate_bench` to `bench.py`
    - Convert `merchant`, `review`, and `external_agent` trace steps to content items; drop payment, delivered item, and `listing_after`
    - Run `gate_purchase` per case with a temp database and key in `tempfile.TemporaryDirectory`, time with `perf_counter`
    - Groups: Attack_Cases (`MANIPULATED`, `OUT_OF_SCOPE`, `INTEGRITY_FAILURE` except payment-only causes), Legitimate_Cases, and two excluded groups (`MERCHANT_MISREPRESENTATION`; `INTEGRITY_FAILURE` with cause `amount_altered` or `cart_hash_altered`) counted with their reasons
    - Metrics: block, ASK_HUMAN, and ALLOW rates per group, false-block rate, block rate by label, `attack_type`, and `cause`, p50 and p95 latency
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7, 11.11_
  - [x] 9.2 Add `render_paygate_section` and `write_paygate_results`, and update `write_results` in `bench.py`
    - Section between `<!-- paygate:begin -->` and `<!-- paygate:end -->`, replaced in place on rerun; includes provider, seed, N, date, the pipeline-test label for `fake` or scripted runs, and a separate "Excluded" table with count and reason per group
    - `results.json` gets a top-level `"paygate"` key; `write_results` preserves an existing PayGate block and key
    - _Requirements: 11.7, 11.8, 11.9, 12.3_
  - [x]* 9.3 Write property test for benchmark conversion and rates
    - **Property 11: Benchmark conversion and rates**
    - **Validates: Requirements 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7**
  - [x]* 9.4 Write property test for the results section writer
    - **Property 12: PayGate results section is idempotent and non-destructive**
    - **Validates: Requirements 11.8**
  - [x] 9.5 Add the `paygate-bench` command to `cli.py`
    - Options `--provider fake|none|anthropic|openai`, `--n`, `--seed`, `--cases-dir`, `--labels`, `--out`, `--min-block-rate`, `--max-false-block-rate`; exit 1 on a missed threshold, 2 on load or provider errors
    - _Requirements: 11.1, 11.10_
  - [x]* 9.6 Write benchmark unit tests
    - Threshold exit codes via Typer's runner, user database untouched, RESULTS.md keeps the IntentTrace block after `write_results`, payment-only and merchant cases land in the excluded tables and in no rate
    - _Requirements: 11.7, 11.8, 11.10, 11.11_

- [x] 10. Sample-case golden test
  - [x] 10.1 Add a golden file of expected Decisions and `tests/test_paygate_samples.py`
    - Convert the committed cases in `benchmark/sample/` with `case_to_request`, generate the golden decisions once with the rule-only path, review them by hand, and assert `gate_purchase` matches
    - _Requirements: 13.4_

- [x] 11. Dashboard Decisions view
  - [x] 11.1 Add `DecisionLabel` and `DecisionRecordItem` to `web/src/types.ts` and `listDecisions`, `getChainStatus`, `decisionEvidenceUrl` to `web/src/api.ts`
    - _Requirements: 10.2, 10.3, 10.6_
  - [x] 11.2 Create `web/src/components/DecisionBadge.tsx`
    - Mirror `VerdictBadge` with the same dark-mode class pattern: green ALLOW, red BLOCK, amber ASK_HUMAN
    - _Requirements: 10.2, 10.7_
  - [x] 11.3 Create `web/src/pages/DecisionsPage.tsx` and wire the `/decisions` route and "Decisions" nav link in `web/src/App.tsx`
    - Chain status banner, `ALL | ALLOW | BLOCK | ASK_HUMAN` filters, newest-first list with timestamp, badge, Reason_Codes, and explanation, inline expansion with highlighted spans and the evidence download link, empty state "No PayGate decisions yet."
    - Existing CSS variables for both themes; layout holds at 390 px
    - `npm run build` succeeds
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7_

- [-] 12. Checkpoint - interfaces and benchmark
  - Ensure all tests pass, ask the user if questions arise.

- [x] 13. CI and README
  - [x] 13.1 Add the `paygate-bench` step to `.github/workflows/ci.yml` after the existing bench step
    - Run `intenttrace paygate-bench --provider fake` once, then set `--min-block-rate` and `--max-false-block-rate` to the measured values minus a margin, and record the baseline in a workflow comment; commit the PayGate section of `benchmark/RESULTS.md` and `results.json`
    - _Requirements: 11.8, 11.10, 13.5, 13.6_
  - [x] 13.2 Add a PayGate section to `README.md`
    - Quickstart for the Python function, REST endpoint, and MCP tool; state that data is synthetic, detection is English-only and bypassable by paraphrase, `ALLOW` is not a guarantee, the data model is AP2-style and not AP2-compliant, and output is not legal advice; list the out-of-scope items and the excluded benchmark groups with their reasons
    - _Requirements: 12.1, 12.3, 12.4, 12.5_
  - [x]* 13.3 Write a test that greps the README for the required limitation phrases
    - _Requirements: 12.1, 12.4, 12.5_

- [~] 14. Final checkpoint - Ensure all tests pass
  - Run `ruff check . && ruff format --check . && pytest -q` and `npm run build` in `web/`. Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate the 12 correctness properties; unit tests validate specific examples and edge cases
- The dashboard has no web test runner; `npm run build` is the only automated check

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "2.1"] },
    { "id": 1, "tasks": ["2.2", "4.1"] },
    { "id": 2, "tasks": ["2.3", "3.1", "4.2", "4.3"] },
    { "id": 3, "tasks": ["3.2", "4.4", "5.1", "5.2"] },
    { "id": 4, "tasks": ["5.3", "5.4", "5.5", "5.6", "7.1", "8.1", "9.1"] },
    { "id": 5, "tasks": ["7.2", "8.2", "9.2", "9.3", "10.1", "11.1", "11.2"] },
    { "id": 6, "tasks": ["9.4", "9.5", "11.3"] },
    { "id": 7, "tasks": ["9.6", "13.1", "13.2"] },
    { "id": 8, "tasks": ["13.3"] }
  ]
}
```
