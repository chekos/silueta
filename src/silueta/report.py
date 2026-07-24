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
        if table.get("not_tabular"):
            lines.append("*Not tabular: no usable table region found — skipped.*")
            lines.append("")
            continue
        if table.get("recovery"):
            notes = ", ".join(f"{key}={value}" for key, value in table["recovery"].items())
            lines.append(f"*Recovery: {notes}*")
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
    relations = profile.get("relations")
    if relations:
        lines.append("## Join candidates")
        lines.append("")
        for rel in relations:
            lines.append(
                f"- `{rel['from_table']}.{rel['from_column']}` → "
                f"`{rel['to_table']}.{rel['to_column']}` "
                f"(containment {rel['containment']:.0%}, name match {rel['name_similarity']:.0%})"
            )
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
        rate = f" {top['match_rate']:.0%}" if top.get("match_rate") is not None else " (name+shape)"
        parts.append(f"{top['type']}{rate}")
    numeric = col.get("numeric")
    if numeric:
        lo, hi = numeric["magnitude_range"]
        parts.append(f"{lo}..{hi}")
    temporal = col.get("temporal")
    if temporal:
        parts.append(f"{temporal['year_span'][0]}–{temporal['year_span'][1]}")
    return ", ".join(parts) if parts else "—"
