---
inclusion: always
---
# Product: IntentTrace

IntentTrace is a forensic investigator for AI agent purchases. Given a purchase record (user instruction, AP2-style signed mandates, agent trace, merchant listing snapshots), it determines whether the purchase was legitimate, out of scope, manipulated before signing, a merchant misrepresentation, or tampered, and produces a dispute-ready evidence packet.

## Principles (apply to every change)
- **Deterministic first.** Integrity, scope, and merchant checks never use an LLM. The LLM is used only where judgment is unavoidable, and its output is validated and cross-checked.
- **Measured, not claimed.** Every accuracy claim comes from `benchmark/RESULTS.md`, labeled with the provider and model that produced it.
- **Never accuse lightly.** False accusations (calling a legitimate purchase manipulated or out of scope) are the most costly error. When evidence is weak, return INCONCLUSIVE.
- **Facts, not legal conclusions.** Reports describe findings. They never state who is legally liable.
- **Synthetic data only.** No real card numbers, no real customers, no real merchants.
- **Honest naming.** Say "AP2-style mandates", never "AP2-compliant".

## Scope
The MVP scope is defined in `.kiro/specs/intenttrace-mvp/`. Do not add features outside it without updating the spec.
