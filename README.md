# IntentTrace

**When an AI agent gets tricked into buying something, who pays? IntentTrace finds out.**

![IntentTrace demo: a MANIPULATED case with the highlighted injection and the replay result](docs/demo.gif)

**Live demo:** https://intenttrace.onrender.com, with PayGate decisions at [/decisions](https://intenttrace.onrender.com/decisions). Free tier, so the first load after idle can take about a minute. Sample data only. On every restart the log resets to the 12 sample decisions.


IntentTrace is a forensic investigator for AI agent purchases. Give it the record of a purchase and it decides whether the purchase was legitimate, out of scope, manipulated, a merchant misrepresentation, or tampered with. It then writes a dispute-ready evidence packet.

It works at two points in a purchase:

- **Before payment, with [PayGate](#paygate-check-before-you-pay).** The agent calls PayGate with the proposed cart and the text it read, and gets `ALLOW`, `BLOCK`, or `ASK_HUMAN` with reasons. Every decision goes into a signed, tamper-evident log.
- **After payment, with the investigator.** Give it the full record of a purchase and it returns a verdict and an evidence packet.

> **AP2-style, not AP2-compliant.** IntentTrace uses a local, AP2-style mandate model (signed intent, cart, and payment mandates). It does not use the official AP2 SDK and makes no claim of AP2 compliance.

## Why we built it

Agent payment protocols prove that a purchase was signed. They do not prove the agent was acting for the user when it signed. A shopping agent that reads a poisoned review can buy the wrong item with a perfectly valid signature, and today nobody can say whether the user, the merchant, or the agent's inputs are at fault. IntentTrace turns that argument into evidence: what the agent read, what it would have chosen without the suspicious text, and which check flags it.

## Who it is for

- **Teams shipping shopping or checkout agents** who want a check that stops a manipulated purchase before money moves (PayGate).
- **Payment providers and dispute teams** who need a defensible first-pass triage of "my agent bought something I didn't want" claims.
- **Agent and shopping-assistant builders** who want to test whether their agent can be redirected, and track it as a regression metric.
- **Merchants and marketplaces** who need to show a listing was not misrepresented, or spot content that manipulates agents.
- **Security and AI-safety researchers** who want a labeled, reproducible benchmark for agent purchase manipulation.

## How it works at a glance

PayGate, before payment:

```mermaid
flowchart LR
    A["Agent: proposed cart,<br/>signed intent, text it read"] --> B["Integrity + scope"]
    B --> C["Injection rules,<br/>best-match, replay"]
    C --> D{"Decision"}
    D --> E["ALLOW / BLOCK / ASK_HUMAN<br/>+ reason codes"]
    D --> F["Signed, hash-chained<br/>decision log"]
```

The investigator, after payment:

```mermaid
flowchart LR
    A["Case file: signed mandates,<br/>agent trace, merchant records"] --> B["1. Integrity<br/>signatures + hash chain"]
    B --> C["2. Scope<br/>cart vs signed constraints"]
    C --> D["3. Merchant consistency<br/>listed vs delivered"]
    D --> E["4. Trace forensics<br/>injection rules + ranking"]
    E --> F["5. Counterfactual replay<br/>re-run without suspicious text"]
    F --> G{"Verdict"}
    G --> H["LEGITIMATE, MANIPULATED, OUT_OF_SCOPE,<br/>MERCHANT_MISREPRESENTATION,<br/>INTEGRITY_FAILURE, INCONCLUSIVE"]
    G --> I["Evidence packet<br/>JSON + Markdown"]
    H --> J["Dashboard, API, MCP tool"]
    I --> J
```

## The problem

Agent payment protocols such as Google's [Agent Payments Protocol (AP2)](https://cloud.google.com/blog/products/ai-machine-learning/announcing-agents-to-payments-ap2-protocol) and the [Agentic Commerce Protocol (ACP)](https://docs.stripe.com/agentic-commerce/protocols/acp) from Stripe, OpenAI, and Meta let AI agents buy things for people. AP2 does this with signed mandates that record what the user authorized.

Signatures protect the data after signing. They say nothing about what happened to the agent before it signed. Shopping agents read untrusted text: product descriptions, reviews, seller Q&A, hidden page elements. [Prompt injection in that content can redirect the agent](https://docs.icme.io/documentation/e-commerce/e-commerce-prompt-injection), and a perfectly valid signature can then sit on a purchase the user never wanted.

Research points the same way:

- [Whispers of Wealth](https://arxiv.org/pdf/2601.22569) red-teams AP2 with prompt injection and reports that indirect injection manipulated product ranking in every trial it ran.
- [TRAP](https://arxiv.org/html/2512.23128v2) benchmarks task-redirecting persuasion against web agents. It reports that agents across six frontier models were susceptible in about a quarter of tasks on average.
- [A systematic security analysis of AP2](https://arxiv.org/html/2608.23858v1) notes that signed mandates protect transaction data after signing, which leaves the pre-signing decision uncovered.

When a dispute arrives, the user, the merchant, and the payment provider each need to know what went wrong. That is the gap IntentTrace targets.

## How it works

1. **Integrity**: verify Ed25519 signatures and the mandate hash chain.
2. **Scope**: check the cart against every constraint the user signed.
3. **Merchant consistency**: compare what was listed, what is listed now, and what was delivered.
4. **Trace forensics**: find suspicious content the agent read, rank the candidates the agent saw, and estimate whether the content drove the decision.
5. **Counterfactual replay**: re-run the agent's decision with the suspicious content removed.

Deterministic stages run first. An LLM is used only where judgment is unavoidable. The output is a verdict (`LEGITIMATE`, `MANIPULATED`, `OUT_OF_SCOPE`, `MERCHANT_MISREPRESENTATION`, `INTEGRITY_FAILURE`, or `INCONCLUSIVE`) plus a JSON and Markdown evidence packet.

## Quickstart

Requires Python 3.11+ (and Node 18+ only if you want to rebuild the dashboard).

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Generate a labeled, signed, synthetic benchmark
intenttrace generate --n 30 --seed 1

# Investigate one of the committed sample cases
intenttrace investigate benchmark/sample/case-0001.json

# Score the investigator (deterministic fake provider)
intenttrace bench --provider fake --n 300 --seed 7

# Load the samples and open the dashboard at http://127.0.0.1:8787
intenttrace load-sample
intenttrace serve

# Rebuild the dashboard (optional)
cd web && npm install && npm run build
```

`intenttrace mcp` starts an MCP server over stdio so other agents can call the investigator as a tool. Run `intenttrace --help` for all options.

## Deploy

A `Dockerfile` and `render.yaml` run the API and the built dashboard as one service on the deterministic `fake` provider, with the sample cases and their PayGate decisions preloaded. No API keys go into the image.

```bash
docker build -t intenttrace-demo .
docker run -p 8787:8787 intenttrace-demo   # http://localhost:8787
```

To host it, create a Render Blueprint from this repo (it reads `render.yaml`). The free tier sleeps when idle, and the database lives in `/tmp`, so submitted cases reset on restart. Vercel is not a fit because the app needs a long-running server and a writable SQLite file.

## Results

> **Pipeline test, not model accuracy.** These numbers come from the deterministic `fake` provider, which tests the pipeline. They say nothing about how a real model performs. A real-provider run (task 13.2) has not been done yet because it needs a paid API key. When it is run, it will be reported separately and labeled with provider and model.

Run: provider `fake` (`fake-deterministic`), prompt version 1, seed 7, 300 synthetic cases. Full tables are in [`benchmark/RESULTS.md`](benchmark/RESULTS.md).

| | Replay on | Replay off |
|---|---|---|
| Macro F1 (5 decidable verdicts) | 0.969 | 0.976 |
| Coverage (not INCONCLUSIVE) | 92.7% | 93.7% |
| False accusation rate | 0.0% | 0.0% |

MANIPULATED recall by attack type (replay on):

| Attack type | Caught | Support | Recall |
|---|---|---|---|
| explicit_instruction | 17 | 17 | 1.000 |
| fake_urgency | 11 | 16 | 0.688 |
| hidden_text | 16 | 16 | 1.000 |
| review_injection | 16 | 16 | 1.000 |
| subtle_persuasion | 0 | 16 | 0.000 |

Subtle persuasion is the hard case: with no explicit instruction to detect, the investigator mostly returns `INCONCLUSIVE` rather than accuse.

## Methodology

- **Synthetic data.** A seeded simulator builds a catalog, user tasks with signed constraints, and candidate sets. It applies five attack types: explicit instruction, fake urgency, hidden text, review injection, and subtle persuasion.
- **Counterfactual labeling.** A case is labeled `MANIPULATED` only when the agent's choice differs from what it would have chosen without the attack. An attack the agent ignored is labeled `LEGITIMATE`.
- **Determinism.** The same seed produces byte-identical cases. Cases are signed with generated keys and validated against [`docs/case-file.schema.json`](docs/case-file.schema.json).
- **Metrics.** Macro F1 over the five decidable verdicts, coverage (share of cases not `INCONCLUSIVE`), false accusation rate, per-attack-type recall, latency, and LLM usage. Each run is scored with replay on and off.
- **Provider labeling.** Every results file names its provider and model. Fake-provider results are never presented as model accuracy.
- **CI gate.** CI fails if macro F1 drops more than 0.03 below the recorded baseline.

## Limitations

- The data model is AP2-style, not the official SDK, and not AP2-compliant.
- The store, merchants, and shopping agents are simulated. All data is synthetic.
- The scripted agent's susceptibility to attacks is a modeling assumption.
- The scripted agent uses the same best-match ranking as the investigator, so the deviation signal is cleaner than it would be for a real agent. A live set with an LLM shopping agent is the honest test, and its results must be reported separately.
- The best-match ranking is a heuristic.
- Detection rules are English-only.
- Results from the fake provider test the pipeline, not model accuracy.
- Reports describe technical findings. They are not legal advice and do not determine liability.

## PayGate: check before you pay

![PayGate Decisions page: verified log, BLOCK filter, a blocked injection with its flagged span and evidence download](docs/paygate-demo.gif)

PayGate is a pre-purchase checkpoint. An AI agent calls it with the signed intent, the cart it plans to buy, and the untrusted text it read. PayGate runs the same integrity, scope, detection, best-match, and replay checks as the investigator and returns `ALLOW`, `BLOCK`, or `ASK_HUMAN` with reason codes. Every decision goes into a signed, hash-chained log. It needs no LLM or API key by default.

Rules run top to bottom. The first match wins.

| # | Condition | Decision | Reason codes |
|---|---|---|---|
| 1 | Signature, hash link, total, or signer check fails | `BLOCK` | `INTEGRITY_*` |
| 2 | Cart breaks a signed constraint | `BLOCK` | `SCOPE_VIOLATION` |
| 3 | Suspicious span, and replay without it changes the choice | `BLOCK` | `INJECTION_DETECTED`, `REPLAY_CHANGED_CHOICE` |
| 4 | Suspicious span, and the chosen item is not the top match | `BLOCK` | `INJECTION_DETECTED`, `BEST_MATCH_DEVIATION` |
| 5 | Suspicious span only | `ASK_HUMAN` | `INJECTION_DETECTED` |
| 6 | Chosen item is not the top match | `ASK_HUMAN` | `BEST_MATCH_DEVIATION` |
| 7 | Nothing found | `ALLOW` | `CLEAN` |

Malformed input returns `ASK_HUMAN` with `INPUT_MALFORMED`. A check that fails, or a log that cannot be written, returns `CHECK_FAILED`. The gate never approves when it is unsure.

### PayGate quickstart

The examples use a request built from a committed sample case. Point `INTENTTRACE_DB` at a scratch file to keep the decision log out of your main database.

```bash
export INTENTTRACE_DB=/tmp/paygate-demo.db

# Build a request from a sample case (a MANIPULATED one: a review injection)
python - <<'EOF'
from intenttrace.bench import case_to_request
from intenttrace.models import CaseFile

case = CaseFile.model_validate_json(open("benchmark/sample/case-0003.json").read())
open("request.json", "w").write(case_to_request(case).model_dump_json())
EOF
```

Python function. It takes a model or a dict, never raises, and writes one log record per call.

```python
import json
from intenttrace.paygate import gate_purchase

result = gate_purchase(json.load(open("request.json")))
print(result.decision, result.reason_codes)
# BLOCK ['INJECTION_DETECTED', 'REPLAY_CHANGED_CHOICE']
```

REST endpoint (start the server with `intenttrace serve`):

```bash
curl -s -X POST http://127.0.0.1:8787/api/paygate/check \
  -H 'Content-Type: application/json' --data @request.json

curl -s 'http://127.0.0.1:8787/api/paygate/decisions?decision=BLOCK&limit=10'
curl -s http://127.0.0.1:8787/api/paygate/chain   # {"valid": true, "first_invalid_id": null, "count": N}
```

A decision of any kind returns HTTP 200. A body that is not valid JSON returns 422. Add `?replay=false` to skip counterfactual replay.

MCP tool. `intenttrace mcp` now exposes `check_purchase(request_json)` next to the three investigator tools. It takes the request as a JSON string and returns the result as a dict.

Benchmark. This converts each generated case into a pre-purchase request and writes the PayGate section of `benchmark/RESULTS.md`:

```bash
intenttrace paygate-bench --provider none --n 300 --seed 7
```

Dashboard. Run `intenttrace paygate-load-sample` to gate the 12 sample cases, then `intenttrace serve` and open the Decisions page at `/decisions`. It lists decisions newest first, filters by decision, shows the flagged spans, links to a Markdown evidence packet, and shows whether the log chain verifies.

The log holds a hash of each request and the span offsets. It does not store the untrusted text. The signing key is created beside the database on first use (`<db>.paygate.key`), or loaded from `PAYGATE_KEY_FILE`.

### PayGate results

> **Pipeline test on synthetic data, not real-world accuracy.** Rules only (no LLM), seed 7, 300 generated cases.

| Group | N | BLOCK | ASK_HUMAN | ALLOW |
|---|---|---|---|---|
| Attack | 141 | 88.7% | 11.3% | 0.0% |
| Legitimate | 99 | 0.0% | 32.3% | 67.7% |

No attack case was allowed and no legitimate case was blocked. Every pre-payment integrity and scope attack was blocked. Of the 81 manipulated cases, 80.2% were blocked: all explicit-instruction, fake-urgency, hidden-text and review-injection cases. Subtle persuasion is the gap: none of its 16 cases were blocked. They all went to `ASK_HUMAN` instead, so none were allowed, but a person has to catch them.

The cost is review load. About a third of legitimate purchases go to `ASK_HUMAN`. Most of them read injected text that did not change the agent's choice, so PayGate flags the text without proof it mattered.

Full tables, including the date, are in the [PayGate section of `benchmark/RESULTS.md`](benchmark/RESULTS.md#paygate-benchmark-pre-purchase-gate).

Two groups are left out of every rate, and the results file counts them separately:

- **`MERCHANT_MISREPRESENTATION`.** The failure appears only after purchase, so there is nothing to check before payment.
- **`INTEGRITY_FAILURE` with cause `amount_altered` or `cart_hash_altered`.** These alter only the payment mandate, which does not exist before payment.

### PayGate limitations

- All data is synthetic. Results say nothing about real-world accuracy.
- Detection rules are English-only. A paraphrased attack can get past them.
- `ALLOW` is not a guarantee of safety. It means the checks found nothing.
- The data model is AP2-style, not AP2-compliant.
- Output is a technical signal. It is not legal advice.

Out of scope:

- Real payment execution, payment rails, card handling, or merchant integrations.
- Official AP2 or ACP SDK interoperability or compliance.
- Human approval workflows. `ASK_HUMAN` only returns the decision.
- Authentication, user accounts, rate limiting, or multi-tenant separation for the HTTP endpoint.
- Non-English detection rules and multimodal content (images, audio, PDFs).
- Detection of post-purchase merchant misrepresentation.
- Training or tuning models, or a required LLM path. The LLM provider stays optional.
- Key management beyond a local key file (no HSM, rotation, or revocation).
- Legal, liability, or chargeback determinations.
- Real-world accuracy claims.

## Built spec-first with Kiro

See [`.kiro/specs/intenttrace-mvp/`](.kiro/specs/intenttrace-mvp/).

## License

MIT
