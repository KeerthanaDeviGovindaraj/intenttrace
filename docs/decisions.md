# Decisions log

Record every ambiguity resolved during the build and every dependency added beyond the spec.
Format: date, task, decision, reason.

## 2026-11-06: Checkpoint A, simulator realism

Context: Reviewing generated cases showed three realism problems. Manipulated think steps said "I'll go with X instead", and named the baseline pick, which leaks ground truth to any downstream detector. Descriptions and instructions came from a single template each. Clean descriptions never contained salesy text, so detectors could rely on "any promotional wording means attack".

Decision:
- Think steps (`sim/agents.py`) present the chosen product as the agent's own best choice, in one of three seeded styles (attack paraphrase, genuine attribute, generic). They never name the baseline and avoid comparatives. Non-switching agents use the same templates.
- Catalog descriptions use 4-6 templates per category. Benign marketing claims go on about 30% of non-attacked candidates, applied per task in `generate.py` (not in the catalog) so attacked products can be excluded and the catalog stays seed-pure.
- Tasks use 8 instruction templates, with optional merchant restriction and quantity. `Task` records `template_id`, `what`, `cap_cents`, `quantity`; `restrict_merchant` keeps text and constraint in sync. `deviation.noun_phrase` was extended to the new wording.
- `models._GUARD_SKIP_KEYS` now also skips `Finding.expected`/`actual`. New random data produced a hash with a Luhn-valid 13+ digit run inside an integrity finding, which crashed the card-number guard. These fields only echo already-validated values. The generated-files test likewise scans only non-hash strings.

Consequences:
- Lexical influence (task 5.4) is high for paraphrase-style manipulated cases and low for attribute/generic styles; recall on influence alone will be lower by design, and the replay stage carries those cases.
- Non-switching agents sometimes paraphrase an attack-like rationale with no attack present; influence scoring must compare against real attack text, not think-step wording.
- Existing seeds produce different cases than before Checkpoint A; no committed benchmark output depends on them.

## 2026-11-07: Checkpoint B, verdict rule fixes and seed manifest

Context: Checkpoint B review of benchmark results showed replay and fallback rules clearing or excusing cases they had not actually tested. Changes authorized by the user; labels, attacks and generator ground truth are unchanged.

Decisions:
- V5 now requires no deviation (replay unchanged AND no deviation -> LEGITIMATE, high). Reason: replay only clears what it tested. An unchanged replay shows the flagged content did not drive the choice, not that the choice was legitimate.
- New V5b: replay unchanged AND deviation -> INCONCLUSIVE (low), finding "deviation not explained by flagged content; possible undetected manipulation." Reason: the deviation is still unexplained, and likely points at manipulation the detector missed.
- New V6a, after V5b and before V6: flagged span in the purchased product's listing or reviews AND deviation -> MANIPULATED (medium), finding "suspicious content attached to purchased product." Reason: attribution signal. Flagged content on the product that was bought, plus a deviation, is evidence even when lexical influence is low (attribute/generic think-step styles). Implemented by matching span step_id to a merchant/review trace step whose product_id is the chosen product; `decide` takes the case for this.
- V9 (no flagged spans AND deviation) is now INCONCLUSIVE (low), was LEGITIMATE (low). Reason: unexplained is not legitimate; we should not clear a purchase we cannot explain.
- `intenttrace generate` writes `manifest.json` (seed, n, generated_at) next to `labels.jsonl`. `bench` in disk mode reads it (from the labels file's directory) so RESULTS.md shows the seed. An explicit `--seed` overrides it. Reason: results were showing seed "unknown".

Consequences:
- Previously LEGITIMATE-low V9 cases and zero-removed-span unchanged replays with deviation now yield INCONCLUSIVE, which lowers coverage but should reduce false clearing of manipulated cases.
