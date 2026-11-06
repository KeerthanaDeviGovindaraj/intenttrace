# IntentTrace: One-Day Build Guide

Kiro follows the spec in `.kiro/specs/intenttrace-mvp/` and the rules in `.kiro/steering/`. Your job: start each phase, check the work at each checkpoint, and make the judgment calls an agent shouldn't make alone. Plan for about 12–13 hours.

## Before you start
1. `cd ~/projects/intenttrace && bash scripts/setup.sh` (creates the Python env and runs checks).
2. Have one LLM API key ready for Phase D (Anthropic or OpenAI).
3. Open the folder in Kiro and confirm it sees the steering files and the spec.
4. Create one Kiro hook: on save of `src/**/*.py`, prompt "Run `pytest -q` and report failures. Fix code, never tests."

## How to drive Kiro
- Open `tasks.md`, start task 1, and let Kiro run tasks in order. Use supervised mode for anything touching benchmark labels or verdict thresholds.
- After each task, check the tests assert something meaningful and nothing was skipped.
- If Kiro is stuck on the same error twice, read its summary and give one clear instruction.

## Schedule
| Time | Phase | You |
|---|---|---|
| 0:00 | Setup | Run setup, open Kiro |
| 0:15 | A: tasks 1–3 | Models, crypto, checks, simulator |
| ~4:00 | Checkpoint A | Generate 30 cases, read two |
| 4:15 | B: tasks 5–7 | Detection, verdicts, evidence, benchmark |
| ~7:15 | Checkpoint B | First benchmark; review three errors; set CI gate |
| 7:30 | C: tasks 9–12 | API, MCP, dashboard, CI |
| ~11:00 | D: tasks 13–14 | Real-model benchmark, README, demo GIF |

## Checkpoint A (10 min)
`intenttrace generate --n 30 --seed 1`, then open one MANIPULATED and one attack-present LEGITIMATE case (see `benchmark/labels.jsonl`). Does the instruction sound real? Is the attack in a description or review? Does the manipulated agent's reasoning echo the attack while the legitimate one ignores it?

## Checkpoint B (15 min)
`intenttrace generate --n 300 --seed 7 && intenttrace bench --provider fake`, then read `benchmark/RESULTS.md`. Check the false accusation rate first. Investigate three misclassified cases with `intenttrace investigate benchmark/cases/<id>.json`. Fix the investigator, never the labels. Enable the CI gate at baseline minus 0.03.

## Phase D: real numbers (30 min)
```
pip install -e ".[llm]"
export INTENTTRACE_LLM_PROVIDER=anthropic   # or openai
export ANTHROPIC_API_KEY=...                # or OPENAI_API_KEY
intenttrace bench --provider anthropic --n 30    # check cost first
intenttrace bench --provider anthropic --n 300
```
Commit that RESULTS.md. Those are the numbers you post.

## Cut list (in this order)
1. LLM shopping-agent live set  2. Dashboard benchmark page  3. MCP server (day 2)  4. Dark mode polish.
Never cut: counterfactual ground truth, false-accusation measurement, the real-model benchmark.

## Honesty rules for publishing
- Say "AP2-style mandates", never "AP2-compliant".
- Quote numbers as "on a synthetic benchmark of N simulated purchases", only from a real-provider RESULTS.md.
- State the main limitation yourself: scripted agents make manipulation easier to detect than real LLM agents.
- Don't claim nobody built this; say what's different (post-hoc forensics of pre-signature manipulation, counterfactual replay, measured false accusation rate).

## LinkedIn post (fill in after Phase D)
> Google's own payment protocol for AI agents says preventing prompt injection is infeasible. So when your AI agent gets tricked into buying something, who pays?
>
> Right now, nobody knows. Signed mandates prove what was authorized, but a manipulated purchase carries a perfectly valid signature.
>
> So I built IntentTrace, a forensic investigator for AI agent purchases. It checks signatures and scope deterministically, analyzes the agent's trace for content that steered its decision, and confirms it by replaying the decision with that content removed.
>
> On a synthetic benchmark of [N] simulated purchases with planted attacks:
> → [X]% of manipulated purchases identified
> → [Y]% false accusation rate on legitimate ones
> → hardest attack type: [type], at [Z]% recall
>
> Built spec-first with Kiro in one day. Code, methodology, and limitations in the comments.

## Resume bullet (fill in after Phase D)
> **IntentTrace – Forensic Investigator for AI Agent Payments** | Python, FastAPI, React, LLM agents, MCP, Ed25519
> • Built an investigator combining deterministic AP2-style mandate verification with LLM trace forensics and counterfactual replay to classify AI agent purchases as legitimate, out of scope, manipulated, or tampered, with dispute-ready evidence packets.
> • Achieved [X]% manipulation recall at a [Y]% false accusation rate on a [N]-case synthetic benchmark with planted prompt-injection attacks, enforced in CI.
