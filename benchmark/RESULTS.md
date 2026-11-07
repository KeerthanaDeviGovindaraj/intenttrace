# IntentTrace benchmark results

> **Pipeline test, not model accuracy.** These numbers come from the deterministic `fake` provider. They test the pipeline, not model accuracy.

| Field | Value |
|---|---|
| Provider | fake |
| Model | fake-deterministic |
| Prompt version | 1 |
| Seed | 7 |
| N (cases) | 300 |
| Date | 2026-11-06 |

## Replay enabled

- Macro F1 (5 decidable verdicts): **0.969**
- Coverage (not INCONCLUSIVE): 92.7%
- False accusation rate: 0.0%
- Latency per case: p50 0.7 ms, p95 1.4 ms

| Verdict | Precision | Recall | F1 | Support |
|---|---|---|---|---|
| LEGITIMATE | 1.000 | 0.990 | 0.995 | 99 |
| MANIPULATED | 1.000 | 0.741 | 0.851 | 81 |
| OUT_OF_SCOPE | 1.000 | 1.000 | 1.000 | 39 |
| MERCHANT_MISREPRESENTATION | 1.000 | 1.000 | 1.000 | 39 |
| INTEGRITY_FAILURE | 1.000 | 1.000 | 1.000 | 42 |

Confusion matrix (rows: ground truth, columns: predicted):

| Truth \ Predicted | LEGITIMATE | MANIPULATED | OUT_OF_SCOPE | MERCHANT_MISREPRESENTATION | INTEGRITY_FAILURE | INCONCLUSIVE |
|---|---|---|---|---|---|---|
| LEGITIMATE | 98 | 0 | 0 | 0 | 0 | 1 |
| MANIPULATED | 0 | 60 | 0 | 0 | 0 | 21 |
| OUT_OF_SCOPE | 0 | 0 | 39 | 0 | 0 | 0 |
| MERCHANT_MISREPRESENTATION | 0 | 0 | 0 | 39 | 0 | 0 |
| INTEGRITY_FAILURE | 0 | 0 | 0 | 0 | 42 | 0 |

MANIPULATED recall by attack type:

| Attack type | Caught | Support | Recall |
|---|---|---|---|
| explicit_instruction | 17 | 17 | 1.000 |
| fake_urgency | 11 | 16 | 0.688 |
| hidden_text | 16 | 16 | 1.000 |
| review_injection | 16 | 16 | 1.000 |
| subtle_persuasion | 0 | 16 | 0.000 |

## Replay disabled

- Macro F1 (5 decidable verdicts): **0.976**
- Coverage (not INCONCLUSIVE): 93.7%
- False accusation rate: 0.0%
- Latency per case: p50 0.6 ms, p95 1.4 ms

| Verdict | Precision | Recall | F1 | Support |
|---|---|---|---|---|
| LEGITIMATE | 1.000 | 0.949 | 0.974 | 99 |
| MANIPULATED | 1.000 | 0.827 | 0.905 | 81 |
| OUT_OF_SCOPE | 1.000 | 1.000 | 1.000 | 39 |
| MERCHANT_MISREPRESENTATION | 1.000 | 1.000 | 1.000 | 39 |
| INTEGRITY_FAILURE | 1.000 | 1.000 | 1.000 | 42 |

Confusion matrix (rows: ground truth, columns: predicted):

| Truth \ Predicted | LEGITIMATE | MANIPULATED | OUT_OF_SCOPE | MERCHANT_MISREPRESENTATION | INTEGRITY_FAILURE | INCONCLUSIVE |
|---|---|---|---|---|---|---|
| LEGITIMATE | 94 | 0 | 0 | 0 | 0 | 5 |
| MANIPULATED | 0 | 67 | 0 | 0 | 0 | 14 |
| OUT_OF_SCOPE | 0 | 0 | 39 | 0 | 0 | 0 |
| MERCHANT_MISREPRESENTATION | 0 | 0 | 0 | 39 | 0 | 0 |
| INTEGRITY_FAILURE | 0 | 0 | 0 | 0 | 42 | 0 |

MANIPULATED recall by attack type:

| Attack type | Caught | Support | Recall |
|---|---|---|---|
| explicit_instruction | 17 | 17 | 1.000 |
| fake_urgency | 16 | 16 | 1.000 |
| hidden_text | 16 | 16 | 1.000 |
| review_injection | 16 | 16 | 1.000 |
| subtle_persuasion | 2 | 16 | 0.125 |

## LLM usage (both passes)

- Calls: 2498
- Input tokens: 403850
- Output tokens: 19524
- Estimated cost: $0.0000

<!-- paygate:begin -->
## PayGate benchmark (pre-purchase gate)

> **Pipeline test on synthetic data. Not a measure of real-world accuracy.**

| Field | Value |
|---|---|
| Provider | none |
| Model | none |
| Seed | 7 |
| N (cases) | 300 |
| Date | 2026-11-07 |

**Headline: PayGate blocked 88.7% of attack cases (n=141) and 0.0% of legitimate cases (n=99).**

| Group | N | BLOCK | ASK_HUMAN | ALLOW |
|---|---|---|---|---|
| Attack | 141 | 88.7% | 11.3% | 0.0% |
| Legitimate | 99 | 0.0% | 32.3% | 67.7% |

False-block rate (legitimate cases blocked): 0.0%

Block rate by label:

| Group | N | Block rate |
|---|---|---|
| INTEGRITY_FAILURE | 21 | 100.0% |
| LEGITIMATE | 99 | 0.0% |
| MANIPULATED | 81 | 80.2% |
| OUT_OF_SCOPE | 39 | 100.0% |

Block rate by attack type:

| Group | N | Block rate |
|---|---|---|
| explicit_instruction | 25 | 68.0% |
| fake_urgency | 24 | 66.7% |
| hidden_text | 24 | 66.7% |
| review_injection | 24 | 66.7% |
| subtle_persuasion | 23 | 0.0% |

Block rate by cause:

| Group | N | Block rate |
|---|---|---|
| attack_changed_choice | 81 | 80.2% |
| attack_present_choice_unchanged | 39 | 0.0% |
| intent_hash_altered | 10 | 100.0% |
| item_altered | 11 | 100.0% |
| no_attack | 60 | 0.0% |
| scope_attribute | 8 | 100.0% |
| scope_expiry | 7 | 100.0% |
| scope_merchant | 8 | 100.0% |
| scope_price | 8 | 100.0% |
| scope_quantity | 8 | 100.0% |

Latency per decision: p50 2.9 ms, p95 3.5 ms

Excluded from every rate above:

| Excluded group | Count | Reason |
|---|---|---|
| merchant_misrepresentation | 39 | The failure appears only after purchase. |
| payment_only_integrity | 21 | These causes alter only the payment mandate, which does not exist before payment. |

<!-- paygate:end -->
