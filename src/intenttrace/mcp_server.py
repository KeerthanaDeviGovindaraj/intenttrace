"""MCP server over stdio (design.md section 16).

The tool functions are plain importable functions; ``create_server`` registers them with the
official ``mcp`` SDK. They read and write the same SQLite store as the REST API.
"""

from __future__ import annotations

import json
import os
from contextlib import closing

from pydantic import ValidationError

from intenttrace.evidence import build_packet, to_markdown
from intenttrace.models import CaseFile
from intenttrace.pipeline import investigate
from intenttrace.store import Store


def _provider():
    from intenttrace.bench import make_provider

    name = os.environ.get("INTENTTRACE_LLM_PROVIDER", "fake").strip().lower() or "fake"
    return make_provider(name)


def investigate_purchase(case_json: str) -> str:
    """Investigate a purchase case file (JSON text) and return the evidence packet as Markdown."""
    try:
        case = CaseFile.model_validate(json.loads(case_json))
    except ValueError as exc:  # json errors and pydantic ValidationError are both ValueErrors
        if isinstance(exc, ValidationError):
            detail = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors())
        else:
            detail = f"Invalid JSON: {exc}"
        raise ValueError(f"Invalid case file: {detail}") from exc
    report = investigate(case, replay=True, provider=_provider())
    with closing(Store()) as store:
        store.save_case(case, report)
    return to_markdown(build_packet(case, report))


def get_case(case_id: str) -> dict:
    """Return the stored case and its investigation report for ``case_id``."""
    with closing(Store()) as store:
        found = store.get_case(case_id)
    if found is None:
        raise ValueError(f"Case not found: {case_id}")
    case, report = found
    return {"case": case.model_dump(mode="json"), "report": report.model_dump(mode="json")}


def list_cases(verdict: str | None = None) -> list[dict]:
    """List stored cases (newest first), optionally filtered by verdict."""
    with closing(Store()) as store:
        return store.list_cases(verdict)


def check_purchase(request_json: str) -> dict:
    """Gate a proposed purchase (GateRequest JSON text) and return the GateResult as a dict."""
    from intenttrace.paygate import gate_purchase, provider_from_env

    try:
        parsed = json.loads(request_json)
    except (ValueError, TypeError, RecursionError):
        parsed = {"__unparseable__": True}  # fails validation -> INPUT_MALFORMED, still logged
    result = gate_purchase(parsed, provider_from_env()[0], replay=True)
    return result.model_dump(mode="json")


def create_server():
    from mcp.server.mcpserver import MCPServer

    server = MCPServer("intenttrace")
    for fn in (investigate_purchase, get_case, list_cases, check_purchase):
        server.tool()(fn)
    return server


def run() -> None:
    """Run the MCP server over stdio."""
    create_server().run(transport="stdio")


if __name__ == "__main__":
    run()
