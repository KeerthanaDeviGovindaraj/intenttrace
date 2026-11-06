# IntentTrace

**When an AI agent gets tricked into buying something, who pays? IntentTrace finds out.**

![IntentTrace demo: a MANIPULATED case with the highlighted injection and the replay result](docs/demo.gif)


IntentTrace is a forensic investigator for AI agent purchases. Give it the record of a purchase and it decides whether the purchase was legitimate, out of scope, manipulated, a merchant misrepresentation, or tampered with. It then writes a dispute-ready evidence packet.

> **AP2-style, not AP2-compliant.** IntentTrace uses a local, AP2-style mandate model (signed intent, cart, and payment mandates). It does not use the official AP2 SDK and makes no claim of AP2 compliance.

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

## Results

> **Pipeline test, not model accuracy.** These numbers come from the deterministic `fake` provider, which tests the pipeline. They say nothing about how a real model performs. Results for a real provider are pending (task 13.2) and will be reported separately and labeled with provider and model.

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

## Built spec-first with Kiro

See [`.kiro/specs/intenttrace-mvp/`](.kiro/specs/intenttrace-mvp/).

## License

MIT
