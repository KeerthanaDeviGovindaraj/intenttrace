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


if __name__ == "__main__":
    app()
