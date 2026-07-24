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
    paths: list[Path] = typer.Argument(..., exists=True, readable=True, help="CSV/Parquet/XLSX files to profile"),
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
def diff(
    old: Path = typer.Argument(..., exists=True, readable=True, help="Earlier profile.json"),
    new: Path = typer.Argument(..., exists=True, readable=True, help="Later profile.json"),
    out: Path | None = typer.Option(None, "--out", "-o", help="Write diff.json"),
    report: Path | None = typer.Option(None, "--report", "-r", help="Write a Markdown diff report"),
    fail_on_change: bool = typer.Option(False, "--fail-on-change", help="Exit 2 if anything changed"),
) -> None:
    """Compare two profiles: schema drift, cardinality jumps, new nulls — with k-suppressed deltas."""
    from .diffing import diff_profiles, render_diff_markdown

    result = diff_profiles(json.loads(old.read_text()), json.loads(new.read_text()))
    if out is not None:
        out.write_text(json.dumps(result, indent=2) + "\n")
        typer.echo(f"wrote {out}")
    markdown = render_diff_markdown(result)
    if report is not None:
        report.write_text(markdown)
        typer.echo(f"wrote {report}")
    else:
        typer.echo(markdown)
    changed = bool(result["tables"] or result["tables_added"] or result["tables_removed"])
    if fail_on_change and changed:
        raise typer.Exit(2)


@app.command()
def version() -> None:
    """Print the silueta version."""
    typer.echo(__version__)


def main() -> None:
    app()
