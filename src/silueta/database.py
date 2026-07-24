"""Profile databases in place via DuckDB ATTACH.

SQLite files are first-class and tested. Postgres/MySQL URIs ride the same
code path through DuckDB's scanner extensions but are experimental until
verified against live servers. Data never leaves the DuckDB process; the
profiler computes the same safe aggregates as for files.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb

from .contract import DEFAULT_K
from .profiler import _profile_view

_INTERNAL_SCHEMAS = {"information_schema", "pg_catalog", "duckdb_internal"}

DB_SUFFIXES = (".sqlite", ".sqlite3", ".db")
DB_SCHEMES = ("postgres://", "postgresql://", "mysql://")


def is_database_path(path: Path) -> bool:
    return path.suffix.lower() in DB_SUFFIXES


def attach_target(target: str) -> tuple[str, str]:
    """Return (attach_sql_fragment, label) for a database target."""
    if target.startswith(DB_SCHEMES):
        db_type = "postgres" if target.startswith(("postgres://", "postgresql://")) else "mysql"
        label = target.split("://", 1)[0]
        return f"ATTACH '{target}' AS _silueta_db (TYPE {db_type}, READ_ONLY)", label
    path = Path(target)
    literal = str(path).replace("'", "''")
    return f"ATTACH '{literal}' AS _silueta_db (TYPE sqlite, READ_ONLY)", path.stem


def profile_database(
    conn: duckdb.DuckDBPyConnection, target: str, k: int = DEFAULT_K
) -> list[tuple[dict[str, Any], str]]:
    """Profile every table in an attached database.

    Returns (table_dict, view_sql) pairs for the relations pass."""
    attach_sql, label = attach_target(target)
    conn.execute(attach_sql)
    tables = conn.execute(
        "SELECT schema_name, table_name FROM duckdb_tables() "
        "WHERE database_name = '_silueta_db' ORDER BY schema_name, table_name"
    ).fetchall()

    profiled: list[tuple[dict[str, Any], str]] = []
    for schema, table_name in tables:
        if schema in _INTERNAL_SCHEMAS:
            continue
        qualified = f'_silueta_db."{schema}"."{table_name}"'
        view_sql = f"SELECT * FROM {qualified}"
        conn.execute(f"CREATE OR REPLACE TEMP VIEW t AS {view_sql}")
        name = f"{label}/{table_name}" if schema in ("main", "public") else f"{label}/{schema}.{table_name}"
        table = _profile_view(conn, name=name, source=target if "://" not in target else label, k=k)
        profiled.append((table, view_sql))
    return profiled
