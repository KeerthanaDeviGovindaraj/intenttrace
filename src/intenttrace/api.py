"""FastAPI app (design.md section 15)."""

from __future__ import annotations

import json
import os
from contextlib import closing
from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from intenttrace.evidence import build_packet, to_markdown
from intenttrace.models import CaseFile
from intenttrace.pipeline import investigate
from intenttrace.store import Store

DEV_ORIGIN = "http://localhost:5173"
DEFAULT_RESULTS = Path("benchmark/results.json")
DEFAULT_DIST = Path("web/dist")


def json_path(loc: tuple) -> str:
    path = "$"
    for part in loc:
        path += f"[{part}]" if isinstance(part, int) else f".{part}"
    return path


def _error(status: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": detail})


def _provider():
    from intenttrace.bench import make_provider

    name = os.environ.get("INTENTTRACE_LLM_PROVIDER", "fake").strip().lower() or "fake"
    return make_provider(name)


def create_app() -> FastAPI:
    app = FastAPI(title="IntentTrace", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[DEV_ORIGIN],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @app.post("/api/investigate")
    async def post_investigate(request: Request, replay: bool = Query(True)):
        raw = await request.body()
        try:
            data = json.loads(raw)
        except ValueError as exc:
            return JSONResponse(
                status_code=422,
                content={"detail": [{"path": "$", "msg": f"Invalid JSON: {exc}"}]},
            )
        try:
            case = CaseFile.model_validate(data)
        except ValidationError as exc:
            errors = [{"path": json_path(e["loc"]), "msg": e["msg"]} for e in exc.errors()]
            return JSONResponse(status_code=422, content={"detail": errors})
        report = investigate(case, replay=replay, provider=_provider())
        with closing(Store()) as store:
            store.save_case(case, report)
        return {"case_id": case.case_id, "report": report.model_dump(mode="json")}

    @app.get("/api/cases")
    def list_cases(verdict: str | None = Query(None)):
        with closing(Store()) as store:
            rows = store.list_cases(verdict)
            out = []
            for row in rows:
                found = store.get_case(row["case_id"])
                summary = build_packet(*found).summary if found else ""
                out.append({**row, "summary": summary})
        return out

    @app.get("/api/cases/{case_id}")
    def get_case(case_id: str):
        with closing(Store()) as store:
            found = store.get_case(case_id)
        if found is None:
            return _error(404, f"Case not found: {case_id}")
        case, report = found
        return {"case": case.model_dump(mode="json"), "report": report.model_dump(mode="json")}

    @app.get("/api/cases/{case_id}/evidence.md")
    def get_evidence(case_id: str):
        with closing(Store()) as store:
            found = store.get_case(case_id)
        if found is None:
            return _error(404, f"Case not found: {case_id}")
        return PlainTextResponse(to_markdown(build_packet(*found)), media_type="text/markdown; charset=utf-8")

    @app.get("/api/benchmark/latest")
    def benchmark_latest():
        path = Path(os.environ.get("INTENTTRACE_RESULTS") or DEFAULT_RESULTS)
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            with closing(Store()) as store:
                body = store.latest_bench_run()
            if body is None:
                return _error(404, "No benchmark results available")
            return json.loads(body)

    dist = Path(os.environ.get("INTENTTRACE_WEB_DIST") or DEFAULT_DIST)
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="web")

    return app


app = create_app()
