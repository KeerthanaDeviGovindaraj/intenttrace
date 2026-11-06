---
inclusion: always
---
# Tech stack and conventions

## Backend (Python 3.12, `src/intenttrace/`)
- Pydantic v2 (models, validation, schemas), `cryptography` (Ed25519), FastAPI + uvicorn (API), Typer (CLI), stdlib `sqlite3` (storage), official `mcp` SDK (MCP server), httpx (tests).
- Real LLM providers are optional extras: `pip install -e ".[llm]"`.
- Full type hints; `from __future__ import annotations` at the top of every module.
- Money is integer cents. Times are ISO 8601 UTC strings. Never use floats for money.
- Randomness only through a seeded `random.Random(seed)` instance passed explicitly; never the global RNG.
- Lint and format with ruff.

## Tests
- pytest; no network, no API keys. Tests use the `fake` LLM provider.
- Every deterministic module has unit tests. Every verdict rule (V1–V10) has its own test.

## Frontend (`web/`)
- Vite + React + TypeScript (strict) + Tailwind CSS + React Router.
- Colors via CSS variables with light and dark values.
- API base URL from `VITE_API_BASE`.

## Commands
- Install: `pip install -e ".[dev]"`
- Check everything: `ruff check . && ruff format --check . && pytest -q`
- Generate and score: `intenttrace generate --n 300 --seed 7 && intenttrace bench --provider fake`
- API: `intenttrace serve` (http://127.0.0.1:8787)
- Web dev: `cd web && npm install && npm run dev`
