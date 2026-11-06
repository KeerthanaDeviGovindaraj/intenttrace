# Implementation Plan: IntentTrace MVP (one-day build)

Rules for every task: implement, write tests, run `ruff check . && ruff format . && pytest -q`, and only mark the task done when everything passes. Commit after each top-level task with message `task N: <title>`. Estimated times assume autonomous execution with a human checkpoint at the end of each phase.

## Phase A: Core engine (target: 4 hours)

- [x] 1. Data model and crypto (~45 min)
  - [x] 1.1 Implement all models in `models.py` exactly as in design.md section 1, including the Luhn card-number guard
  - [x] 1.2 Implement `crypto.py`: canonical JSON, sign, verify, mandate_hash, generate_keypair
  - [x] 1.3 Export the CaseFile JSON Schema to `docs/case-file.schema.json` via a small script `scripts/export_schema.py`
  - [x] 1.4 Tests: sign/verify round trip, tamper detection on every mandate, card-number rejection, schema export
  - _Requirements: 1.1–1.5, 2.1_

- [x] 2. Integrity, scope, and merchant checks (~60 min)
  - [x] 2.1 `checks/integrity.py` with every check in design.md section 3
  - [x] 2.2 `checks/scope.py` with every constraint in design.md section 4
  - [x] 2.3 `checks/merchant.py` with material versus non-material differences (design.md section 5)
  - [x] 2.4 Shared `Finding` model in `models.py` (kind, detail, field, expected, actual, step_ids, spans, method)
  - [x] 2.5 Tests: one passing and one failing case per check, including expiry and human-present signer rule
  - _Requirements: 2.2–2.4, 3.1–3.3, 4.1–4.3_

- [x] 3. Simulator and case generator (~90 min)
  - [x] 3.1 `sim/catalog.py` seeded catalog (design.md 11.1)
  - [x] 3.2 `sim/tasks.py` instructions plus constraints plus candidate sets (11.2)
  - [x] 3.3 `sim/attacks.py` with all five attack types (11.3)
  - [x] 3.4 `forensics/deviation.py` best-match ranking (6.2); the scripted agent reuses it
  - [x] 3.5 `sim/agents.py` ScriptedAgent with seeded susceptibility and think-step generation (11.4); LLMAgent stub behind the provider interface
  - [x] 3.6 `sim/generate.py` with the bucket mix, counterfactual labeling, signing with generated keys, and the output layout (11.5)
  - [x] 3.7 CLI command `intenttrace generate --n --seed`
  - [x] 3.8 Tests: determinism (same seed gives byte-identical output), every bucket filled, MANIPULATED label only when the counterfactual differs, attack-present-but-not-fooled cases labeled LEGITIMATE, every generated case passes validation
  - _Requirements: 8.1–8.7_

- [x] 4. Checkpoint A (human, ~10 min)
  - Run `intenttrace generate --n 30 --seed 1` and open two case files. Confirm they read like real purchases.

## Phase B: Investigation pipeline (target: 3 hours)

- [x] 5. Detection and influence (~60 min)
  - [x] 5.1 `forensics/detect.py` rules R1–R5 with spans and rule IDs (6.1)
  - [x] 5.2 `llm/base.py` provider protocol with usage tracking; `llm/fake.py`; `llm/prompts.py` with PROMPT_VERSION
  - [x] 5.3 LLM classifier integration in detection, recording `method`
  - [x] 5.4 `forensics/influence.py` lexical score plus LLM judgment and the combination rule (6.3)
  - [x] 5.5 Tests: each rule fires on its example and not on bland descriptions; hidden-text detection; influence math; LLM failure degrades to lexical with an `llm_unavailable` finding
  - _Requirements: 5.1–5.5, 12.1–12.3_

- [x] 6. Replay, verdict, evidence (~60 min)
  - [x] 6.1 `forensics/replay.py` (section 7) for scripted agents
  - [x] 6.2 `verdict.py` with rules V1–V10 and thresholds in `config.py`
  - [x] 6.3 `pipeline.py` with `investigate(case, replay=True, provider=...) -> Report` running stages in order with early exit
  - [x] 6.4 `evidence.py` JSON and Markdown packets with templated summaries and the legal notice
  - [x] 6.5 CLI command `intenttrace investigate`
  - [x] 6.6 Tests: one test per verdict rule; replay changed and unchanged; full pipeline on hand-built cases; Markdown contains the notice
  - _Requirements: 6.1–6.4, 7.1–7.4_

- [x] 7. Benchmark (~45 min)
  - [x] 7.1 `bench.py` metrics from design.md section 12, replay on and off, per attack type, usage and cost
  - [x] 7.2 RESULTS.md and results.json writers, with provider labeling rules (Requirement 12.4)
  - [x] 7.3 CLI `intenttrace bench` with threshold flags and exit codes
  - [x] 7.4 Generate and commit the 12-case sample in `benchmark/sample/` (2 per ground-truth bucket) plus `tests/test_sample_cases.py`
  - [x] 7.5 Test: `--n 30` smoke run completes with the fake provider
  - _Requirements: 9.1–9.5_

- [x] 8. Checkpoint B (human, ~15 min)
  - Run `intenttrace generate --n 300 --seed 7 && intenttrace bench --provider fake`. Read RESULTS.md. Look at three misclassified cases and decide whether the investigator or the spec is wrong. Record the baseline; add the CI gate at baseline minus 0.03 macro F1.

## Phase C: Interfaces (target: 3.5 hours)

- [x] 9. Store, API, CLI wiring (~45 min)
  - [x] 9.1 `store.py` with the schema in section 13
  - [x] 9.2 `api.py` endpoints in section 15, CORS for the dev server, static dashboard serving
  - [x] 9.3 CLI `serve` and `load-sample`
  - [x] 9.4 Tests with TestClient for every endpoint, including 422 on invalid cases
  - _Requirements: 10.1, 10.2, 10.4_

- [x] 10. MCP server (~30 min)
  - [x] 10.1 `mcp_server.py` with the three tools over stdio (section 16); check the installed `mcp` package's docs for the current server API
  - [x] 10.2 CLI `intenttrace mcp`
  - [x] 10.3 Tests calling the tool functions directly
  - _Requirements: 10.3_

- [x] 11. Dashboard (~2 hours)
  - [x] 11.1 Scaffold `web/` with Vite React-TS, Tailwind, React Router; strict TypeScript; types mirroring the Report and CaseFile models
  - [x] 11.2 Case list page with filters and badges
  - [x] 11.3 Case detail page: verdict banner, intent-versus-cart table, trace timeline with highlighted spans, replay card, evidence download
  - [x] 11.4 Benchmark page: metric cards, confusion matrix, recall by attack type
  - [x] 11.5 Light and dark themes; check at 390px width
  - [x] 11.6 `npm run build` succeeds; the API serves `web/dist`
  - _Requirements: 11.1–11.4_

- [x] 12. CI (~15 min)
  - [x] 12.1 Enable the benchmark gate and web build jobs in `.github/workflows/ci.yml`
  - _Requirements: 13.2_

## Phase D: Real-model run and launch (target: 1.5 hours)

- [~] 13. Real-provider benchmark (human-supervised, ~30 min)
  - [x] 13.1 Implement the real provider (Anthropic or OpenAI) in `llm/`
  - [~] 13.2 Run `intenttrace bench --provider <real> --n 300` and commit RESULTS.md labeled with provider and model (not run: no API key available; README states this)
  - [~] 13.3 Optional: a 20-case live set with the LLM shopping agent, reported separately (not run: no API key available)
  - _Requirements: 9.3, 12.1, 12.4_

- [x] 14. README and demo (~45 min)
  - [x] 14.1 README: problem (with sources), how it works, quickstart, results table from RESULTS.md, methodology, limitations, "AP2-style, not AP2-compliant" note
  - [x] 14.2 Record a 30–60 second demo GIF: open a MANIPULATED case, show the highlighted injection and the replay result
  - _Requirements: 13.3_
