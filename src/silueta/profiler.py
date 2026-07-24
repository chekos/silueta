"""Core profiler: DuckDB computes safe aggregates; nothing else leaves the scan.

Raw values exist only inside the DuckDB process and the in-process semantic
validators. The profile dict built here is the only output surface, and it is
constructed exclusively from aggregates, masks, and derived scalars.
"""

from __future__ import annotations

import datetime as dt
import math
import re
from pathlib import Path
from typing import Any

import duckdb

from . import __version__
from .contract import CONTRACT_STATEMENT, DEFAULT_K, small_table, suppress_mask_counts
from .masks import mask_sql
from .semantic import HIGH_SEVERITY, classify_sample, mrn_heuristic, name_signals

_CODE_NAME = re.compile(r"zip|postal|phone|ssn|npi|dea|mrn|code|(^|[_\s])id([_\s]|$)|acct|account", re.IGNORECASE)

SAMPLE_SIZE = 1000
NUMERIC_TYPES = ("TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT", "FLOAT", "DOUBLE", "DECIMAL")
TEMPORAL_TYPES = ("DATE", "TIMESTAMP")

INT32_MIN, INT32_MAX = -(2**31), 2**31 - 1
INT64_MIN, INT64_MAX = -(2**63), 2**63 - 1


def _q(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _magnitude(value: float | int | None) -> str | None:
    """Order of magnitude as a value-free string, e.g. 12345 -> '10^4'."""
    if value is None:
        return None
    value = float(value)
    if value == 0:
        return "0"
    sign = "-" if value < 0 else ""
    return f"{sign}10^{int(math.floor(math.log10(abs(value))))}"


def _reader_sql(path: Path) -> str:
    suffix = path.suffix.lower()
    literal = str(path).replace("'", "''")
    if suffix == ".csv":
        return f"read_csv_auto('{literal}')"
    if suffix == ".parquet":
        return f"read_parquet('{literal}')"
    raise ValueError(f"Unsupported input type: {path.name}")


PROMOTION_THRESHOLD = 0.98


def _recover_types(
    conn: duckdb.DuckDBPyConnection, source: str
) -> tuple[str, dict[str, dict[str, Any]]]:
    """Promote all-VARCHAR columns to real types via TRY_CAST when nearly all
    non-null values cast cleanly. Returns SQL for a typed view over `source`
    and per-column recovery facts ({to, confidence})."""
    columns = [row[0] for row in conn.execute(f'DESCRIBE "{source}"').fetchall()]
    selects: list[str] = []
    recovered: dict[str, dict[str, Any]] = {}
    for name in columns:
        q = _q(name)
        nonnull, as_int, as_num, as_date, as_ts = conn.execute(
            f"SELECT count({q}), "
            f"sum(CASE WHEN TRY_CAST({q} AS BIGINT) IS NOT NULL THEN 1 ELSE 0 END), "
            f"sum(CASE WHEN TRY_CAST(replace({q}, ',', '') AS DOUBLE) IS NOT NULL THEN 1 ELSE 0 END), "
            f"sum(CASE WHEN TRY_CAST({q} AS DATE) IS NOT NULL THEN 1 ELSE 0 END), "
            f"sum(CASE WHEN TRY_CAST({q} AS TIMESTAMP) IS NOT NULL THEN 1 ELSE 0 END) "
            f'FROM "{source}" WHERE {q} IS NOT NULL'
        ).fetchone()
        target: str | None = None
        rate = 0.0
        if nonnull:
            rates = {
                "BIGINT": (as_int or 0) / nonnull,
                "DOUBLE": (as_num or 0) / nonnull,
                "DATE": (as_date or 0) / nonnull,
                "TIMESTAMP": (as_ts or 0) / nonnull,
            }
            for candidate in ("BIGINT", "DATE", "TIMESTAMP", "DOUBLE"):
                if rates[candidate] >= PROMOTION_THRESHOLD:
                    target, rate = candidate, rates[candidate]
                    break
        if target == "DOUBLE":
            selects.append(f"TRY_CAST(replace({q}, ',', '') AS DOUBLE) AS {q}")
            recovered[name] = {"to": target, "confidence": round(rate, 4)}
        elif target:
            selects.append(f"TRY_CAST({q} AS {target}) AS {q}")
            recovered[name] = {"to": target, "confidence": round(rate, 4)}
        else:
            selects.append(q)
    return f'SELECT {", ".join(selects)} FROM "{source}"', recovered


def profile_table(
    conn: duckdb.DuckDBPyConnection, path: Path, k: int = DEFAULT_K
) -> dict[str, Any]:
    conn.execute(f"CREATE OR REPLACE TEMP VIEW t AS SELECT * FROM {_reader_sql(path)}")
    return _profile_view(conn, name=path.stem, source=path.name, k=k)


def profile_workbook(
    conn: duckdb.DuckDBPyConnection, path: Path, k: int = DEFAULT_K
) -> list[tuple[dict[str, Any], str | None]]:
    """Profile every sheet of a workbook via messy-table recovery.

    Returns (table_dict, view_sql) pairs; view_sql reproduces the typed view
    on this connection (the raw sheet temp tables persist for the run)."""
    from .workbook import extract_tables, register_table

    tables: list[tuple[dict[str, Any], str | None]] = []
    for i, sheet in enumerate(extract_tables(path)):
        name = f"{path.stem}/{sheet.sheet_name}"
        if sheet.not_tabular:
            tables.append(
                (
                    {
                        "name": name,
                        "source": path.name,
                        "rows": 0,
                        "columns": [],
                        "not_tabular": True,
                        "alerts": [{"kind": "not_tabular", "detail": sheet.recovery.get("reason", "")}],
                    },
                    None,
                )
            )
            continue
        raw = f"_silueta_sheet_{path.stem}_{i}"
        register_table(conn, sheet, raw)
        typed_sql, recovered = _recover_types(conn, raw)
        conn.execute(f"CREATE OR REPLACE TEMP VIEW t AS {typed_sql}")
        table = _profile_view(conn, name=name, source=path.name, k=k)
        if sheet.recovery:
            table["recovery"] = sheet.recovery
        for col in table["columns"]:
            if col["name"] in recovered:
                col["type_recovered"] = recovered[col["name"]]
                if "typed_as_text_numeric" not in col.get("alerts", []):
                    col.setdefault("alerts", []).append("recovered_from_text")
        tables.append((table, typed_sql))
    return tables


def _profile_view(
    conn: duckdb.DuckDBPyConnection, name: str, source: str, k: int
) -> dict[str, Any]:
    columns = conn.execute("DESCRIBE t").fetchall()
    row_count = conn.execute("SELECT count(*) FROM t").fetchone()[0]

    table: dict[str, Any] = {
        "name": name,
        "source": source,
        "rows": row_count,
        "columns": [],
        "alerts": [],
    }

    if small_table(row_count, k):
        table["suppressed_small_table"] = True
        table["alerts"].append({"kind": "small_table", "detail": f"fewer than k={k} rows; structure only"})
        table["columns"] = [{"name": name, "physical_type": ctype} for name, ctype, *_ in columns]
        return table

    for name, ctype, *_ in columns:
        table["columns"].append(_profile_column(conn, name, ctype, row_count, k))

    _table_alerts(table)
    return table


def _profile_column(
    conn: duckdb.DuckDBPyConnection, name: str, ctype: str, row_count: int, k: int
) -> dict[str, Any]:
    q = _q(name)
    base_type = ctype.split("(")[0].upper()
    col: dict[str, Any] = {"name": name, "physical_type": ctype}

    nonnull, distinct = conn.execute(
        f"SELECT count({q}), count(DISTINCT {q}) FROM t"
    ).fetchone()
    null_count = row_count - nonnull
    col["nulls"] = {"count": null_count, "rate": round(null_count / row_count, 4)}

    if distinct <= 1:
        # Constant columns report nothing that could pin the value:
        # no mask, no lengths, no ranges (mask + length + a column name can identify it).
        col["constant"] = True
        return col

    col["distinct"] = distinct
    col["uniqueness_ratio"] = round(distinct / nonnull, 4) if nonnull else 0.0

    signals = name_signals(name)
    if signals:
        col["name_signals"] = signals

    if base_type in NUMERIC_TYPES:
        col["numeric"] = _numeric_facts(conn, q, base_type, ctype)
        if base_type not in ("FLOAT", "DOUBLE", "DECIMAL") and (signals or _CODE_NAME.search(name)):
            _int_code_facts(conn, q, col, k, signals)
    elif base_type in TEMPORAL_TYPES:
        col["temporal"] = _temporal_facts(conn, q)
    elif base_type == "VARCHAR":
        col.update(_string_facts(conn, q, k))
        col.setdefault("semantic", []).extend(_sample_semantic(conn, q))

    if mrn_heuristic(name, col.get("uniqueness_ratio"), col.get("masks", [])):
        col.setdefault("semantic", []).append(
            {"type": "mrn_like", "match_rate": None, "severity": "high", "basis": "name+shape"}
        )
    if col.get("semantic") == []:
        del col["semantic"]

    _column_alerts(col)
    return col


def _sample_semantic(conn: duckdb.DuckDBPyConnection, expr: str) -> list[dict[str, Any]]:
    """Sample non-null values and classify in-process; only aggregates return."""
    sample = [
        row[0]
        for row in conn.execute(
            f"SELECT v FROM (SELECT {expr} AS v FROM t WHERE {expr} IS NOT NULL) "
            f"USING SAMPLE reservoir({SAMPLE_SIZE} ROWS)"
        ).fetchall()
    ]
    return [{**vars(h), "basis": "values"} for h in classify_sample([str(v) for v in sample])]


def _int_code_facts(
    conn: duckdb.DuckDBPyConnection, q: str, col: dict[str, Any], k: int, signals: list[str]
) -> None:
    """Integer columns named like codes/ids get string-form shape analysis:
    zips, phones, and identifiers sniffed as numbers lose their shape otherwise."""
    cast = f"CAST({q} AS VARCHAR)"
    masks, suppressed_share = _mask_facts(conn, cast, k)
    if masks:
        col["masks"] = masks
        if suppressed_share:
            col["masks_suppressed_share"] = suppressed_share
    col.setdefault("semantic", []).extend(_sample_semantic(conn, cast))
    if "us_zip" in signals:
        lo = conn.execute(f"SELECT min({q}) FROM t").fetchone()[0]
        if lo is not None and lo < 10000:
            col.setdefault("alerts", []).append("possible_leading_zero_loss")


def _numeric_facts(
    conn: duckdb.DuckDBPyConnection, q: str, base_type: str, ctype: str
) -> dict[str, Any]:
    lo, hi, zeros, negatives = conn.execute(
        f"SELECT min({q}), max({q}), "
        f"sum(CASE WHEN {q} = 0 THEN 1 ELSE 0 END), "
        f"sum(CASE WHEN {q} < 0 THEN 1 ELSE 0 END) FROM t"
    ).fetchone()
    facts: dict[str, Any] = {
        # min/max stay internal; only magnitudes are emitted.
        "magnitude_range": [_magnitude(lo), _magnitude(hi)],
        "zero_count": int(zeros or 0),
        "negative_count": int(negatives or 0),
    }
    if base_type in ("TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT"):
        facts["fits_int32"] = lo is not None and lo >= INT32_MIN and hi <= INT32_MAX
        facts["fits_int64"] = lo is not None and lo >= INT64_MIN and hi <= INT64_MAX
    if base_type == "DECIMAL" and "(" in ctype:
        precision_scale = ctype[ctype.index("(") + 1 : ctype.index(")")]
        facts["precision_scale"] = precision_scale
    return facts


def _temporal_facts(conn: duckdb.DuckDBPyConnection, q: str) -> dict[str, Any]:
    lo_year, hi_year = conn.execute(
        f"SELECT year(min({q})), year(max({q})) FROM t"
    ).fetchone()
    # Year granularity only; ages 90+ would need capping when we emit age-like
    # derivations — raw dates and full spans never appear.
    return {"year_span": [lo_year, hi_year]}


def _string_facts(conn: duckdb.DuckDBPyConnection, q: str, k: int) -> dict[str, Any]:
    (min_len, max_len, avg_len, blanks, upper_ct, lower_ct, nonascii_ct, nonnull) = conn.execute(
        f"SELECT min(length({q})), max(length({q})), round(avg(length({q})), 1), "
        f"sum(CASE WHEN trim({q}) = '' THEN 1 ELSE 0 END), "
        f"sum(CASE WHEN {q} = upper({q}) AND {q} <> lower({q}) THEN 1 ELSE 0 END), "
        f"sum(CASE WHEN {q} = lower({q}) AND {q} <> upper({q}) THEN 1 ELSE 0 END), "
        f"sum(CASE WHEN regexp_matches({q}, '[^\\x00-\\x7F]') THEN 1 ELSE 0 END), "
        f"count({q}) FROM t"
    ).fetchone()
    facts: dict[str, Any] = {
        "length": {"min": min_len, "max": max_len, "avg": float(avg_len) if avg_len is not None else None},
        "blank_rate": round((blanks or 0) / nonnull, 4) if nonnull else 0.0,
        "casing": {
            "upper_rate": round((upper_ct or 0) / nonnull, 4) if nonnull else 0.0,
            "lower_rate": round((lower_ct or 0) / nonnull, 4) if nonnull else 0.0,
        },
        "non_ascii_rate": round((nonascii_ct or 0) / nonnull, 4) if nonnull else 0.0,
    }

    masks, suppressed_share = _mask_facts(conn, q, k)
    facts["masks"] = masks
    if suppressed_share:
        facts["masks_suppressed_share"] = suppressed_share

    # Typed-as-text recovery signal: how much of a VARCHAR column is castable.
    castable = conn.execute(
        f"SELECT round(sum(CASE WHEN TRY_CAST({q} AS DOUBLE) IS NOT NULL THEN 1 ELSE 0 END)"
        f" / count({q}), 4), "
        f"round(sum(CASE WHEN TRY_CAST({q} AS DATE) IS NOT NULL THEN 1 ELSE 0 END)"
        f" / count({q}), 4) FROM t WHERE {q} IS NOT NULL"
    ).fetchone()
    numeric_rate, date_rate = float(castable[0] or 0), float(castable[1] or 0)
    if numeric_rate >= 0.95:
        facts["castable"] = {"as": "numeric", "rate": numeric_rate}
    elif date_rate >= 0.95:
        facts["castable"] = {"as": "date", "rate": date_rate}
    return facts


def _mask_facts(
    conn: duckdb.DuckDBPyConnection, expr: str, k: int
) -> tuple[list[dict[str, Any]], float]:
    mask_counts = conn.execute(
        f"SELECT {mask_sql(expr)} AS mask, count(*) AS n FROM t WHERE {expr} IS NOT NULL "
        f"GROUP BY 1 ORDER BY 2 DESC"
    ).fetchall()
    return suppress_mask_counts(mask_counts, k)


def _column_alerts(col: dict[str, Any]) -> None:
    alerts: list[str] = []
    if col.get("constant"):
        alerts.append("constant_column")
    ratio = col.get("uniqueness_ratio")
    if ratio is not None and 0.99 <= ratio < 1.0:
        alerts.append("near_unique")
    if col["nulls"]["rate"] >= 0.9 and not col.get("constant"):
        alerts.append("mostly_null")
    if col.get("castable"):
        alerts.append(f"typed_as_text_{col['castable']['as']}")
    casing = col.get("casing")
    if casing and 0.15 <= casing["upper_rate"] <= 0.85 and casing["upper_rate"] + casing["lower_rate"] > 0.3:
        alerts.append("mixed_casing")
    for hit in col.get("semantic", []):
        if hit["type"] in HIGH_SEVERITY:
            alerts.append(f"sensitive_{hit['type']}")
    if "dob" in col.get("name_signals", []) and (
        col.get("temporal") or col.get("castable", {}).get("as") == "date"
    ):
        alerts.append("sensitive_dob")
    existing = col.get("alerts", [])
    merged = existing + [a for a in alerts if a not in existing]
    if merged:
        col["alerts"] = merged


def _table_alerts(table: dict[str, Any]) -> None:
    for col in table["columns"]:
        for alert in col.get("alerts", []):
            if alert.startswith("sensitive_"):
                table["alerts"].append({"kind": alert, "column": col["name"]})


def profile_paths(paths: list[Path], k: int = DEFAULT_K) -> dict[str, Any]:
    conn = duckdb.connect()
    profile: dict[str, Any] = {
        "silueta": {
            "version": __version__,
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "k": k,
            "contract": CONTRACT_STATEMENT,
        },
        "tables": [],
    }
    view_sqls: dict[str, str] = {}
    for path in paths:
        if path.suffix.lower() in (".xlsx", ".xls"):
            for table, view_sql in profile_workbook(conn, path, k):
                profile["tables"].append(table)
                if view_sql:
                    view_sqls[table["name"]] = view_sql
        else:
            table = profile_table(conn, path, k)
            profile["tables"].append(table)
            view_sqls[table["name"]] = f"SELECT * FROM {_reader_sql(path)}"

    from .relations import detect_relations

    relations = detect_relations(conn, profile["tables"], view_sqls)
    if relations:
        profile["relations"] = relations
    return profile
