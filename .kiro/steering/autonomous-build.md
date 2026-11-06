---
inclusion: always
---
# Rules for autonomous building

These rules exist because this project is built largely by an agent in one day. Follow them strictly.

1. **Work task by task, in order.** Do not start a task until the previous one passes `ruff check . && ruff format --check . && pytest -q`.
2. **Tests define done.** Write the tests listed in the task. Never delete, skip, or weaken a test to make it pass. If a test seems wrong, stop and explain why instead of changing it.
3. **Never tune the benchmark to the investigator.** Do not change ground-truth labeling, the bucket mix, or attack text to improve scores. Improve the investigator instead.
4. **Never hardcode case IDs, seeds, or expected answers** inside investigator code.
5. **Stay inside the spec.** If something in the spec is ambiguous, choose the simplest reading, note it in `docs/decisions.md`, and continue.
6. **No new dependencies** beyond those in `pyproject.toml` and the web stack in `tech.md` without recording the reason in `docs/decisions.md`.
7. **No network in tests.** Use the fake provider.
8. **Commit after each top-level task** with message `task N: <title>`.
9. **Keep functions small and pure** where possible; I/O stays in `store.py`, `api.py`, `cli.py`, and `llm/` providers.
10. **When stuck for more than two attempts on the same error,** stop and summarize the problem rather than trying random changes.
