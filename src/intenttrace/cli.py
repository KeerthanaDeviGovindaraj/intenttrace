"""IntentTrace CLI. Commands are added task by task (see .kiro/specs/intenttrace-mvp/tasks.md)."""

from __future__ import annotations

import typer

from intenttrace import __version__

app = typer.Typer(help="Forensic investigator for AI agent purchases.", no_args_is_help=True)


@app.command()
def version() -> None:
    """Print the IntentTrace version."""
    typer.echo(__version__)


if __name__ == "__main__":
    app()
