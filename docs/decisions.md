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
