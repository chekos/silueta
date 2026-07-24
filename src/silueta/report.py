"""Render a profile dict as a compact human-readable Markdown report."""

from __future__ import annotations

from typing import Any


def render_markdown(profile: dict[str, Any]) -> str:
    meta = profile["silueta"]
    lines = [
        "# silueta profile",
        "",
        f"*silueta {meta['version']} · {meta['generated_at']} · k={meta['k']}*",
        "",
        f"> {meta['contract']}",
        "",
    ]
    for table in profile["tables"]:
        lines.append(f"## {table['name']} ({table['source']}) — {table['rows']:,} rows")
        lines.append("")
        if table.get("suppressed_small_table"):
            lines.append("*Structure only: table has fewer than k rows.*")
            lines.append("")
            lines.append(", ".join(f"`{c['name']}` ({c['physical_type']})" for c in table["columns"]))
            lines.append("")
            continue
        lines.append("| column | type | nulls | distinct | shape |")
        lines.append("|---|---|---|---|---|")
        for col in table["columns"]:
            lines.append(
                f"| `{col['name']}` | {col['physical_type']} "
                f"| {col['nulls']['rate']:.1%} | {_distinct(col)} | {_shape(col)} |"
            )
        lines.append("")
        alerts = table.get("alerts") or []
        col_alerts = [
            f"`{col['name']}`: {', '.join(col['alerts'])}"
            for col in table["columns"]
            if col.get("alerts")
        ]
        if alerts or col_alerts:
            lines.append("**Alerts:** " + "; ".join(col_alerts))
            lines.append("")
    return "\n".join(lines)


def _distinct(col: dict[str, Any]) -> str:
    if col.get("constant"):
        return "constant"
    ratio = col.get("uniqueness_ratio")
    return f"{col.get('distinct', '—')} ({ratio:.0%} unique)" if ratio is not None else "—"


def _shape(col: dict[str, Any]) -> str:
    if col.get("constant"):
        return "—"
    parts: list[str] = []
    if col.get("masks"):
        parts.append("`" + col["masks"][0]["mask"] + "`")
    if col.get("semantic"):
        top = col["semantic"][0]
        parts.append(f"{top['type']} {top['match_rate']:.0%}")
    numeric = col.get("numeric")
    if numeric:
        lo, hi = numeric["magnitude_range"]
        parts.append(f"{lo}..{hi}")
    temporal = col.get("temporal")
    if temporal:
        parts.append(f"{temporal['year_span'][0]}–{temporal['year_span'][1]}")
    return ", ".join(parts) if parts else "—"
