"""Foreign-key candidate detection via exact containment.

At workbook scale, exact set containment is one DuckDB semi-join over
distinct values — no sketches, no extra state, nothing serialized. Only
derived scalars (containment ratio, name similarity) reach the profile.
"""

from __future__ import annotations

import re
from typing import Any

import duckdb

MIN_KEY_UNIQUENESS = 0.95
MIN_CARDINALITY = 20  # floor on both sides so low-cardinality enums don't dominate
MIN_CONTAINMENT = 0.95
MAX_RELATIONS = 20

_INT_TYPES = {"TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT"}


def _q(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _base_type(ctype: str) -> str:
    base = ctype.split("(")[0].upper()
    return "INT" if base in _INT_TYPES else base


def _tokens(name: str) -> set[str]:
    return {t for t in re.split(r"[^a-zA-Z0-9]+|_", re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name).lower()) if t}


def name_similarity(fk_name: str, key_name: str, key_table: str) -> float:
    fk, key = _tokens(fk_name), _tokens(key_name)
    if not fk or not key:
        return 0.0
    jaccard = len(fk & key) / len(fk | key)
    table_bonus = 0.25 if _tokens(key_table) & fk else 0.0
    return round(min(1.0, jaccard + table_bonus), 4)


def detect_relations(
    conn: duckdb.DuckDBPyConnection, tables: list[dict[str, Any]], view_sqls: dict[str, str]
) -> list[dict[str, Any]]:
    """`tables` are profiled table dicts; `view_sqls` maps table name -> SQL
    that reproduces the table's typed view on this connection."""
    # Materialize views for every profiled table that has data.
    views: dict[str, str] = {}
    for i, table in enumerate(tables):
        if table["name"] not in view_sqls or table.get("not_tabular") or table.get("suppressed_small_table"):
            continue
        view = f"_silueta_rel_{i}"
        conn.execute(f'CREATE OR REPLACE TEMP VIEW "{view}" AS {view_sqls[table["name"]]}')
        views[table["name"]] = view

    keys = []  # (table, column, base_type)
    fks = []
    for table in tables:
        if table["name"] not in views:
            continue
        for col in table["columns"]:
            distinct = col.get("distinct")
            if distinct is None or distinct < MIN_CARDINALITY:
                continue
            base = _base_type(col["physical_type"])
            if base not in ("VARCHAR", "INT"):
                continue
            entry = (table["name"], col["name"], base)
            fks.append(entry)
            if col.get("uniqueness_ratio", 0) >= MIN_KEY_UNIQUENESS:
                keys.append(entry)

    relations: list[dict[str, Any]] = []
    for key_table, key_col, key_type in keys:
        for fk_table, fk_col, fk_type in fks:
            if fk_type != key_type:
                continue
            if fk_table == key_table and fk_col == key_col:
                continue
            containment = _containment(conn, views[fk_table], fk_col, views[key_table], key_col)
            if containment >= MIN_CONTAINMENT:
                relations.append(
                    {
                        "from_table": fk_table,
                        "from_column": fk_col,
                        "to_table": key_table,
                        "to_column": key_col,
                        "containment": containment,
                        "name_similarity": name_similarity(fk_col, key_col, key_table),
                    }
                )

    relations.sort(key=lambda r: (-r["containment"], -r["name_similarity"]))
    return relations[:MAX_RELATIONS]


def _containment(
    conn: duckdb.DuckDBPyConnection, fk_view: str, fk_col: str, key_view: str, key_col: str
) -> float:
    total, contained = conn.execute(
        f"SELECT count(*), "
        f'sum(CASE WHEN v IN (SELECT {_q(key_col)} FROM "{key_view}") THEN 1 ELSE 0 END) '
        f'FROM (SELECT DISTINCT {_q(fk_col)} AS v FROM "{fk_view}" WHERE {_q(fk_col)} IS NOT NULL)'
    ).fetchone()
    return round((contained or 0) / total, 4) if total else 0.0
