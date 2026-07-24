"""Profile diffing: what changed between two vendor drops.

Deltas are k-suppressed like everything else — two profiles of consecutive
drops differing by one row must not single that row out, so small count
deltas report as "<k" rather than exact numbers.
"""

from __future__ import annotations

from typing import Any

from .contract import DEFAULT_K


def _delta(old: int | None, new: int | None, k: int) -> Any:
    if old is None or new is None:
        return None
    diff = new - old
    if diff == 0:
        return 0
    if abs(diff) < k:
        return f"+<{k}" if diff > 0 else f"-<{k}"
    return diff


def diff_profiles(old: dict[str, Any], new: dict[str, Any], k: int = DEFAULT_K) -> dict[str, Any]:
    old_tables = {t["name"]: t for t in old.get("tables", [])}
    new_tables = {t["name"]: t for t in new.get("tables", [])}

    result: dict[str, Any] = {
        "silueta": {"diff": True, "k": k},
        "tables_added": sorted(set(new_tables) - set(old_tables)),
        "tables_removed": sorted(set(old_tables) - set(new_tables)),
        "tables": [],
    }

    for name in sorted(set(old_tables) & set(new_tables)):
        entry = _diff_table(old_tables[name], new_tables[name], k)
        if entry:
            result["tables"].append(entry)
    return result


def _diff_table(old: dict[str, Any], new: dict[str, Any], k: int) -> dict[str, Any] | None:
    old_cols = {c["name"]: c for c in old.get("columns", [])}
    new_cols = {c["name"]: c for c in new.get("columns", [])}

    entry: dict[str, Any] = {"name": new["name"]}
    row_delta = _delta(old.get("rows"), new.get("rows"), k)
    if row_delta:
        entry["rows"] = {"old": old.get("rows"), "new": new.get("rows"), "delta": row_delta}

    added = sorted(set(new_cols) - set(old_cols))
    removed = sorted(set(old_cols) - set(new_cols))
    if added:
        entry["columns_added"] = added
    if removed:
        entry["columns_removed"] = removed

    changed: list[dict[str, Any]] = []
    for cname in sorted(set(old_cols) & set(new_cols)):
        change = _diff_column(old_cols[cname], new_cols[cname], k)
        if change:
            changed.append(change)
    if changed:
        entry["columns_changed"] = changed

    return entry if len(entry) > 1 else None


def _diff_column(old: dict[str, Any], new: dict[str, Any], k: int) -> dict[str, Any] | None:
    change: dict[str, Any] = {"name": new["name"]}

    if old.get("physical_type") != new.get("physical_type"):
        change["type"] = {"old": old.get("physical_type"), "new": new.get("physical_type")}

    old_null = (old.get("nulls") or {}).get("rate")
    new_null = (new.get("nulls") or {}).get("rate")
    if old_null is not None and new_null is not None and abs(new_null - old_null) >= 0.01:
        change["null_rate"] = {"old": old_null, "new": new_null}

    distinct_delta = _delta(old.get("distinct"), new.get("distinct"), k)
    if distinct_delta:
        change["distinct_delta"] = distinct_delta

    old_mask = (old.get("masks") or [{}])[0].get("mask")
    new_mask = (new.get("masks") or [{}])[0].get("mask")
    if old_mask != new_mask:
        change["top_mask"] = {"old": old_mask, "new": new_mask}

    old_alerts = set(old.get("alerts", []))
    new_alerts = set(new.get("alerts", []))
    if new_alerts - old_alerts:
        change["alerts_added"] = sorted(new_alerts - old_alerts)

    if old.get("constant") != new.get("constant"):
        change["constant"] = {"old": bool(old.get("constant")), "new": bool(new.get("constant"))}

    return change if len(change) > 1 else None


def render_diff_markdown(diff: dict[str, Any]) -> str:
    lines = ["# silueta diff", ""]
    if diff["tables_added"]:
        lines.append("**Tables added:** " + ", ".join(f"`{t}`" for t in diff["tables_added"]))
    if diff["tables_removed"]:
        lines.append("**Tables removed:** " + ", ".join(f"`{t}`" for t in diff["tables_removed"]))
    if not diff["tables"] and not diff["tables_added"] and not diff["tables_removed"]:
        lines.append("No changes.")
    for table in diff["tables"]:
        lines.append(f"## {table['name']}")
        if "rows" in table:
            lines.append(f"- rows: {table['rows']['old']:,} → {table['rows']['new']:,} ({table['rows']['delta']})")
        for key in ("columns_added", "columns_removed"):
            if key in table:
                lines.append(f"- {key.replace('_', ' ')}: " + ", ".join(f"`{c}`" for c in table[key]))
        for col in table.get("columns_changed", []):
            details = [f"{key}={value}" for key, value in col.items() if key != "name"]
            lines.append(f"- `{col['name']}`: " + "; ".join(details))
        lines.append("")
    return "\n".join(lines) + "\n"
