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


if __name__ == "__main__":
    app()
