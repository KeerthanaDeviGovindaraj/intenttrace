"""IntentTrace CLI. Commands are added task by task (see .kiro/specs/intenttrace-mvp/tasks.md)."""

from __future__ import annotations

from pathlib import Path

import typer

from intenttrace import __version__

app = typer.Typer(help="Forensic investigator for AI agent purchases.", no_args_is_help=True)


@app.callback()
def main() -> None:
    """Forensic investigator for AI agent purchases."""


@app.command()
def version() -> None:
    """Print the IntentTrace version."""
    typer.echo(__version__)


@app.command()
def generate(
    n: int = typer.Option(300, "--n", min=1, help="Number of cases to generate."),
    seed: int = typer.Option(7, "--seed", help="Deterministic RNG seed."),
    out: Path = typer.Option(Path("benchmark"), "--out", help="Output directory."),
) -> None:
    """Generate a labeled benchmark of signed cases."""
    from collections import Counter

    from intenttrace.sim.generate import generate as generate_cases

    generated = generate_cases(n, seed, out)
    counts = Counter(g.label["label"] for g in generated)
    typer.echo(f"Generated {len(generated)} cases (seed={seed}) in {out}")
    for label in sorted(counts):
        typer.echo(f"  {label}: {counts[label]}")


def _json_path(loc: tuple) -> str:
    path = "$"
    for part in loc:
        path += f"[{part}]" if isinstance(part, int) else f".{part}"
    return path


def _select_provider():
    """Fake provider unless INTENTTRACE_LLM_PROVIDER names another one (none are wired up yet)."""
    import os

    name = os.environ.get("INTENTTRACE_LLM_PROVIDER", "fake").strip().lower() or "fake"
    if name == "fake":
        from intenttrace.llm.fake import FakeProvider

        return FakeProvider()
    typer.echo(f"Unsupported INTENTTRACE_LLM_PROVIDER: {name!r} (only 'fake' is available)", err=True)
    raise typer.Exit(code=2)


@app.command()
def investigate(
    case_file: Path = typer.Argument(..., metavar="CASE_JSON", help="Path to a case file."),
    no_replay: bool = typer.Option(False, "--no-replay", help="Skip counterfactual replay."),
    out: Path | None = typer.Option(None, "--out", help="Write the Markdown evidence packet here."),
) -> None:
    """Investigate a case and produce an evidence packet."""
    from pydantic import ValidationError

    from intenttrace.evidence import build_packet, to_markdown
    from intenttrace.models import CaseFile
    from intenttrace.pipeline import investigate as run_investigation

    try:
        text = case_file.read_text(encoding="utf-8")
    except OSError as exc:
        typer.echo(f"Cannot read {case_file}: {exc.strerror or exc}", err=True)
        raise typer.Exit(code=2) from exc
    try:
        case = CaseFile.model_validate_json(text)
    except ValidationError as exc:
        typer.echo(f"Invalid case file {case_file}:", err=True)
        for err in exc.errors():
            typer.echo(f"  {_json_path(err['loc'])}: {err['msg']}", err=True)
        raise typer.Exit(code=2) from exc

    provider = _select_provider()
    report = run_investigation(case, replay=not no_replay, provider=provider)
    packet = build_packet(case, report)
    markdown = to_markdown(packet)

    typer.echo(f"Verdict: {report.verdict}")
    typer.echo(f"Confidence: {report.confidence}")
    typer.echo(f"Rule: {report.rule_id}")
    typer.echo(f"Summary: {packet.summary}")
    if out is not None:
        out.write_text(markdown, encoding="utf-8")
        typer.echo(f"Evidence packet written to {out}")
    else:
        typer.echo("")
        typer.echo(markdown)


@app.command()
def bench(
    provider: str = typer.Option("fake", "--provider", help="LLM provider name."),
    n: int | None = typer.Option(
        None, "--n", min=1, help="Generate N cases in memory instead of reading disk."
    ),
    seed: int | None = typer.Option(None, "--seed", help="Seed (used with --n; recorded in results)."),
    min_macro_f1: float | None = typer.Option(None, "--min-macro-f1", help="Fail if macro F1 is lower."),
    max_false_accusation: float | None = typer.Option(
        None, "--max-false-accusation", help="Fail if the false accusation rate is higher."
    ),
    cases_dir: Path = typer.Option(Path("benchmark/cases"), "--cases-dir", help="Cases to score."),
    labels: Path = typer.Option(Path("benchmark/labels.jsonl"), "--labels", help="Ground-truth labels."),
    out: Path = typer.Option(Path("benchmark"), "--out", help="Where RESULTS.md and results.json go."),
) -> None:
    """Score the investigator against labeled cases and write RESULTS.md / results.json."""
    from intenttrace.bench import load_cases, make_provider, read_manifest_seed, run_bench, write_results
    from intenttrace.sim.generate import build_cases

    try:
        llm = make_provider(provider.strip().lower())
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc

    if n is not None:
        used_seed = 7 if seed is None else seed
        generated = build_cases(n, used_seed)
        cases = [g.case for g in generated]
        label_map = {g.case.case_id: g.label for g in generated}
    else:
        used_seed = seed if seed is not None else read_manifest_seed(labels.parent / "manifest.json")
        try:
            cases, label_map = load_cases(cases_dir, labels)
        except (OSError, ValueError) as exc:
            typer.echo(f"Cannot load benchmark cases: {exc}", err=True)
            raise typer.Exit(code=2) from exc

    results = run_bench(cases, label_map, llm, seed=used_seed)
    json_path, md_path = write_results(results, out)
    head = results["replay_on"]
    typer.echo(f"Provider: {results['provider']} ({results['model']}), N={results['n']}")
    if results["pipeline_test_only"]:
        typer.echo("Note: fake provider numbers are pipeline tests, not model accuracy.")
    typer.echo(f"Macro F1: {head['macro_f1']:.3f}")
    typer.echo(f"Coverage: {head['coverage']:.3f}")
    typer.echo(f"False accusation rate: {head['false_accusation_rate']:.3f}")
    typer.echo(f"Wrote {md_path} and {json_path}")

    failed = False
    if min_macro_f1 is not None and head["macro_f1"] < min_macro_f1:
        typer.echo(f"FAIL: macro F1 {head['macro_f1']:.3f} < {min_macro_f1}", err=True)
        failed = True
    if max_false_accusation is not None and head["false_accusation_rate"] > max_false_accusation:
        typer.echo(
            f"FAIL: false accusation rate {head['false_accusation_rate']:.3f} > {max_false_accusation}",
            err=True,
        )
        failed = True
    if failed:
        raise typer.Exit(code=1)


@app.command()
def serve(
    port: int = typer.Option(8787, "--port", help="Port to listen on."),
    host: str = typer.Option("127.0.0.1", "--host", help="Interface to bind."),
) -> None:
    """Serve the API (and the dashboard when web/dist exists)."""
    import uvicorn

    from intenttrace.api import app as api_app

    uvicorn.run(api_app, host=host, port=port)


@app.command()
def mcp() -> None:
    """Start the MCP server over stdio."""
    from intenttrace import mcp_server

    mcp_server.run()


@app.command("load-sample")
def load_sample(
    sample_dir: Path = typer.Option(Path("benchmark/sample"), "--dir", help="Directory of sample cases."),
) -> None:
    """Investigate the sample cases and store them with their reports."""
    from contextlib import closing

    from intenttrace.models import CaseFile
    from intenttrace.pipeline import investigate as run_investigation
    from intenttrace.store import Store

    files = sorted(sample_dir.glob("case-*.json"))
    if not files:
        typer.echo(f"No sample cases found in {sample_dir}", err=True)
        raise typer.Exit(code=2)
    provider = _select_provider()
    with closing(Store()) as store:
        for f in files:
            case = CaseFile.model_validate_json(f.read_text(encoding="utf-8"))
            store.save_case(case, run_investigation(case, replay=True, provider=provider))
    typer.echo(f"Stored {len(files)} sample cases in {store.path}")


if __name__ == "__main__":
    app()
