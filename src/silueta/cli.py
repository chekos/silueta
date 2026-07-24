"""silueta command line interface."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from . import __version__
from .contract import DEFAULT_K
from .profiler import profile_paths
from .report import render_markdown

app = typer.Typer(help="Profile the shape of your data — never the values.", no_args_is_help=True)


@app.command()
def scan(
    paths: list[Path] = typer.Argument(..., exists=True, readable=True, help="CSV/Parquet files to profile"),
    out: Path = typer.Option(Path("profile.json"), "--out", "-o", help="Where to write profile.json"),
    report: Path | None = typer.Option(None, "--report", "-r", help="Also write a Markdown report"),
    k: int = typer.Option(
        DEFAULT_K, "--k", help="Suppression threshold: stats from values in fewer than k rows are suppressed"
    ),
) -> None:
    """Profile datasets into a value-free profile.json (and optional report.md)."""
    profile = profile_paths(paths, k=k)
    out.write_text(json.dumps(profile, indent=2, default=str) + "\n")
    typer.echo(f"wrote {out}")
    if report is not None:
        report.write_text(render_markdown(profile))
        typer.echo(f"wrote {report}")
    for table in profile["tables"]:
        n_alerts = len(table.get("alerts", [])) + sum(
            len(c.get("alerts", [])) for c in table["columns"]
        )
        typer.echo(f"  {table['name']}: {table['rows']:,} rows, {len(table['columns'])} columns, {n_alerts} alerts")


@app.command()
def version() -> None:
    """Print the silueta version."""
    typer.echo(__version__)


def main() -> None:
    app()
