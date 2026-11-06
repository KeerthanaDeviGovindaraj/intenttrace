---
inclusion: always
---
# Repository structure

```
src/intenttrace/
  models.py          case file, mandates, findings, report models
  crypto.py          canonical JSON, Ed25519 sign/verify, hashes
  config.py          verdict thresholds and constants
  checks/            integrity.py, scope.py, merchant.py   (deterministic)
  forensics/         detect.py, deviation.py, influence.py, replay.py
  llm/               base.py, fake.py, prompts.py, <real provider>.py
  sim/               catalog.py, tasks.py, attacks.py, agents.py, generate.py
  pipeline.py        investigate(): runs the stages in order
  verdict.py         rules V1–V10
  evidence.py        evidence packet JSON + Markdown
  bench.py           metrics, RESULTS.md
  store.py           SQLite
  api.py             FastAPI app
  mcp_server.py      MCP tools
  cli.py             Typer entry point
web/                 React dashboard
benchmark/           sample/ (committed), cases/ (generated, gitignored), RESULTS.md, results.json
docs/                case-file.schema.json, design notes
scripts/             small utilities (schema export)
tests/               mirrors src layout
```
