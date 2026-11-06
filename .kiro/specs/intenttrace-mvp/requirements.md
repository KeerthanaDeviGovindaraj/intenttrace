# Requirements: IntentTrace MVP

## Introduction

AI agents can now pay on a user's behalf through agent payment protocols such as AP2 (Agent Payments Protocol) and ACP (Agentic Commerce Protocol). These protocols use signed mandates to prove what a user authorized, but they cannot detect when an agent was manipulated by prompt injection *before* it signed. A manipulated purchase carries a perfectly valid signature.

IntentTrace is a forensic investigator for AI agent purchases. Given the full record of a purchase (user instruction, signed mandates, agent trace, merchant page snapshots), it determines what happened and produces a dispute-ready evidence packet. It ships with a simulator that generates purchases with planted attacks and exact ground truth, so its accuracy is measured, not claimed.

**Scope of this MVP (one-day build):** AP2-style mandate data model implemented locally (not the official AP2 SDK), simulated store and shopping agent, five-stage investigation pipeline, benchmark with CI gate, REST API, MCP server, and a web dashboard.

**Out of scope for the MVP:** interoperability with the official AP2 or ACP reference implementations, real payment rails, real merchant integrations, user accounts, and legal liability determinations.

## Glossary

- **Intent Mandate**: user-signed record of what the agent may buy (constraints such as max price, category, allowed merchants, quantity, expiry).
- **Cart Mandate**: signed record of the exact cart (merchant, items, prices, total). Signed by the user (human-present flow) or the agent (human-not-present flow).
- **Payment Mandate**: signed record that a payment was made for a specific cart.
- **Case file**: one complete purchase record, the unit of investigation.
- **Trace**: the agent's ordered steps (observations, reasoning, tool calls, decision) leading to the purchase.
- **Untrusted content**: anything in the trace that did not come from the user (product descriptions, reviews, merchant messages, other agents' messages).
- **Verdict**: one of `LEGITIMATE`, `OUT_OF_SCOPE`, `MANIPULATED`, `MERCHANT_MISREPRESENTATION`, `INTEGRITY_FAILURE`, `INCONCLUSIVE`.
- **Accusing verdict**: any verdict other than `LEGITIMATE` and `INCONCLUSIVE`.
- **Replay**: re-running the agent's decision with suspicious content removed, to test whether that content changed the outcome.

## Success criteria

1. `intenttrace generate` produces a reproducible benchmark (same seed, same cases) with exact ground truth.
2. `intenttrace bench` reports per-verdict precision and recall, macro F1, coverage, and false accusation rate, and writes `benchmark/RESULTS.md`.
3. CI runs lint, tests, and the benchmark gate on every push, with no network access and no API keys.
4. The dashboard shows a case timeline with suspicious content highlighted and the verdict with its evidence.
5. The MCP server lets an AI assistant investigate a case.

## Requirements

### Requirement 1: Case file format

**User story:** As an investigator, I want a single, validated format for purchase records, so that every case is analyzed the same way.

**Acceptance criteria**
1. THE SYSTEM SHALL define the case file as Pydantic v2 models: `CaseFile`, `IntentMandate`, `CartMandate`, `PaymentMandate`, `TraceStep`, `ListingSnapshot`, `AgentConfig`.
2. WHEN a case file is loaded THE SYSTEM SHALL validate it and report every validation error with its JSON path.
3. THE SYSTEM SHALL export the case file JSON Schema to `docs/case-file.schema.json`.
4. THE SYSTEM SHALL treat `AgentConfig` and the post-purchase listing snapshot as optional, and every analysis stage SHALL degrade gracefully when they are absent.
5. Case files SHALL contain only synthetic data; THE SYSTEM SHALL NOT accept or store real card numbers (reject any field matching a payment card number pattern that passes the Luhn check).

### Requirement 2: Mandate integrity

**User story:** As an investigator, I want to know whether any mandate was altered after signing, so that tampering is caught with certainty.

**Acceptance criteria**
1. THE SYSTEM SHALL sign and verify mandates with Ed25519 over a canonical JSON encoding (keys sorted, no insignificant whitespace, UTF-8).
2. THE SYSTEM SHALL verify that the Cart Mandate references the hash of the Intent Mandate and that the Payment Mandate references the hash of the Cart Mandate.
3. IF any signature fails or any hash reference does not match THEN THE SYSTEM SHALL return verdict `INTEGRITY_FAILURE` with the failing mandate and field.
4. THE SYSTEM SHALL record which party signed each mandate (user or agent).

### Requirement 3: Scope verification

**User story:** As an investigator, I want to know whether the purchase stayed within what the user authorized, so that clear violations are caught without AI judgment.

**Acceptance criteria**
1. THE SYSTEM SHALL check the cart against every Intent Mandate constraint: max total price, max unit price, allowed categories, allowed merchants, max quantity, required attributes, and expiry.
2. IF any constraint is violated THEN THE SYSTEM SHALL return verdict `OUT_OF_SCOPE` listing every violated constraint with the expected and actual values.
3. Scope checks SHALL be deterministic and SHALL NOT call an LLM.

### Requirement 4: Merchant consistency

**User story:** As an investigator, I want to know whether the merchant changed what it was selling, so that merchant misrepresentation is not blamed on the agent or user.

**Acceptance criteria**
1. WHEN a post-purchase listing snapshot is present THE SYSTEM SHALL compare it with the snapshot the agent saw at purchase time on price, title, and every attribute.
2. WHEN the delivered-item record is present THE SYSTEM SHALL compare its attributes with the listing at purchase time.
3. IF a material difference is found (price, a required attribute, or a declared attribute of the purchased item) THEN THE SYSTEM SHALL return verdict `MERCHANT_MISREPRESENTATION` with a field-level diff.

### Requirement 5: Trace forensics

**User story:** As an investigator, I want to know whether untrusted content steered the agent's choice, so that manipulation before signing can be identified.

**Acceptance criteria**
1. THE SYSTEM SHALL label every trace step's source as trusted (user) or untrusted (merchant, review, external agent).
2. THE SYSTEM SHALL detect suspicious spans in untrusted content using deterministic pattern rules (instruction-like text, text addressed to AI agents, hidden-text markers) and an LLM classifier, recording which method flagged each span.
3. THE SYSTEM SHALL compute a deterministic best-match ranking of the candidate items the agent observed, using only the user's instruction and the Intent Mandate, and SHALL record whether the chosen item deviates from the top-ranked candidate.
4. THE SYSTEM SHALL estimate an influence score from 0 to 1 for whether the agent's recorded reasoning relied on flagged content, combining lexical overlap (deterministic) with an LLM judgment.
5. Every forensic finding SHALL reference the trace step IDs and character spans it is based on.

### Requirement 6: Counterfactual replay

**User story:** As an agent platform investigating its own agent, I want to test whether removing suspicious content changes the decision, so that manipulation can be confirmed rather than inferred.

**Acceptance criteria**
1. WHEN the case includes a replayable `AgentConfig` THE SYSTEM SHALL re-run the agent's decision step with all flagged spans removed, using the same seed.
2. IF the replayed choice differs from the original choice THEN THE SYSTEM SHALL record `replay: changed`; otherwise `replay: unchanged`.
3. WHEN no replayable config is present THE SYSTEM SHALL record `replay: unavailable` and continue.
4. THE SYSTEM SHALL support running the full pipeline with replay disabled (`--no-replay`), so issuers without agent access can be simulated.

### Requirement 7: Verdict and evidence packet

**User story:** As a merchant, issuer, or consumer, I want a clear verdict with evidence, so that I can act on a dispute.

**Acceptance criteria**
1. THE SYSTEM SHALL produce exactly one primary verdict per case using the ordered decision rules in design.md, plus a list of secondary findings.
2. THE SYSTEM SHALL attach a confidence level (`high`, `medium`, `low`) and the rule that produced the verdict.
3. THE SYSTEM SHALL produce an evidence packet (JSON plus Markdown) containing the verdict, every finding with its references, the intent-versus-cart comparison, flagged content excerpts, the replay result, and a plain-English summary.
4. The evidence packet SHALL describe facts and SHALL NOT state legal liability conclusions; it SHALL include a notice that it is not legal advice.

### Requirement 8: Simulator and benchmark generation

**User story:** As the maintainer, I want to generate realistic purchases with planted attacks and exact ground truth, so that accuracy can be measured honestly.

**Acceptance criteria**
1. THE SYSTEM SHALL generate a synthetic catalog (at least 5 categories, 40+ products, multiple merchants) with prices and attributes.
2. THE SYSTEM SHALL generate user tasks with natural-language instructions and matching Intent Mandates.
3. THE SYSTEM SHALL provide an attack library with at least these types: explicit instruction to AI agents, hidden-text instruction, fake urgency or discount claim, review injection, and subtle persuasion with no explicit instruction.
4. THE SYSTEM SHALL provide a scripted shopping agent with configurable, seeded susceptibility per attack type, and an optional LLM shopping agent.
5. THE SYSTEM SHALL derive ground truth by counterfactual generation: a case is labeled `MANIPULATED` only if the agent's choice with the attack differs from its choice without the attack. Cases containing an attack that did not change the choice SHALL be labeled `LEGITIMATE`.
6. THE SYSTEM SHALL generate `OUT_OF_SCOPE`, `MERCHANT_MISREPRESENTATION`, and `INTEGRITY_FAILURE` cases with known causes.
7. `intenttrace generate --n <N> --seed <S>` SHALL be fully reproducible and write cases to `benchmark/cases/` plus `benchmark/labels.jsonl`.

### Requirement 9: Benchmark scoring

**User story:** As the maintainer, I want accuracy measured and regressions blocked, so that every claim I make is backed by numbers.

**Acceptance criteria**
1. `intenttrace bench` SHALL report per-verdict precision and recall, macro F1, a confusion matrix, coverage (share of cases not `INCONCLUSIVE`), and false accusation rate (share of `LEGITIMATE` cases given an accusing verdict).
2. THE SYSTEM SHALL report results separately with replay enabled and disabled, and separately for each attack type.
3. THE SYSTEM SHALL record the LLM provider and model used, total LLM calls, tokens, estimated cost, and latency.
4. THE SYSTEM SHALL write `benchmark/RESULTS.md` and `benchmark/results.json`.
5. WHEN run with `--min-macro-f1 <x>` or `--max-false-accusation <y>` THE SYSTEM SHALL exit non-zero if a threshold is missed.

### Requirement 10: API and MCP server

**User story:** As a developer or AI assistant, I want to submit cases programmatically, so that IntentTrace fits into other tools.

**Acceptance criteria**
1. THE SYSTEM SHALL expose REST endpoints: `POST /api/investigate`, `GET /api/cases`, `GET /api/cases/{id}`, `GET /api/cases/{id}/evidence.md`, `GET /api/benchmark/latest`.
2. THE SYSTEM SHALL persist cases and reports in SQLite.
3. THE SYSTEM SHALL provide an MCP server over stdio with tools `investigate_purchase`, `get_case`, and `list_cases`.
4. The API SHALL bind to `127.0.0.1` by default.

### Requirement 11: Dashboard

**User story:** As a reviewer, I want to see a case visually, so that I understand the verdict in seconds.

**Acceptance criteria**
1. THE SYSTEM SHALL list cases with verdict badges, confidence, and filters by verdict.
2. WHEN a case is opened THE SYSTEM SHALL show the verdict banner, the trace as a timeline with untrusted steps marked and flagged spans highlighted, the intent-versus-cart table, the replay result, and an evidence download button.
3. THE SYSTEM SHALL provide a benchmark page with the confusion matrix and headline metrics.
4. THE SYSTEM SHALL support light and dark mode and be usable at 390px width.

### Requirement 12: LLM providers

**Acceptance criteria**
1. THE SYSTEM SHALL use one provider interface with a deterministic `fake` provider (default in tests and CI) and at least one real provider selected by environment variable.
2. THE SYSTEM SHALL validate every LLM response against a schema and retry once on invalid output; on a second failure the stage SHALL degrade (record `llm_unavailable`) rather than crash.
3. THE SYSTEM SHALL never send anything to an LLM except synthetic case content.
4. RESULTS.md SHALL state clearly which provider produced the numbers; numbers from the `fake` provider SHALL be labeled as pipeline tests, not model accuracy.

### Requirement 13: Quality

**Acceptance criteria**
1. Every deterministic module SHALL have unit tests; tests SHALL need no network and no API keys.
2. CI SHALL run ruff, pytest, the benchmark gate (fake provider), and the web build.
3. THE README SHALL include the problem, a demo GIF, quickstart, benchmark results, methodology, and limitations.
