# IntentTrace

**When an AI agent gets tricked into buying something, who pays? IntentTrace finds out.**

AI agents can now make purchases using signed payment mandates (AP2, ACP). The signatures prove *what* was authorized, but not whether the agent was manipulated by prompt injection *before* it signed. IntentTrace is a forensic investigator: give it the record of an agent purchase and it determines whether the purchase was legitimate, out of scope, manipulated, a merchant misrepresentation, or tampered, then produces a dispute-ready evidence packet.

> Status: in development. Demo, benchmark results, and methodology land at launch.

## How it works
1. **Integrity**: verify Ed25519 signatures and the mandate hash chain.
2. **Scope**: check the cart against every constraint the user signed.
3. **Merchant consistency**: compare what was listed, what is listed now, and what was delivered.
4. **Trace forensics**: find suspicious content the agent read, rank the candidates the agent saw, and estimate whether the content drove the decision.
5. **Counterfactual replay**: re-run the agent's decision with the suspicious content removed.

Deterministic stages run first; an LLM is used only where judgment is unavoidable.

## Honest scope
- AP2-*style* mandates implemented locally; not the official AP2 SDK, not AP2-compliant.
- All data is synthetic: simulated store, merchants, and shopping agents.
- Reports describe technical findings. They are not legal advice and do not determine liability.

## Built spec-first with Kiro
See [`.kiro/specs/intenttrace-mvp/`](.kiro/specs/intenttrace-mvp/).

## License
MIT
