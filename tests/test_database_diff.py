from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path

import pytest

from silueta.diffing import diff_profiles
from silueta.profiler import profile_paths
from silueta.report import render_markdown


@pytest.fixture()
def sqlite_db(tmp_path: Path) -> Path:
    path = tmp_path / "warehouse.sqlite"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE members (member_id TEXT PRIMARY KEY, joined TEXT)")
    conn.execute("CREATE TABLE claims (claim_id TEXT, member_id TEXT, amount REAL)")
    for i in range(50):
        conn.execute("INSERT INTO members VALUES (?, ?)", (f"MBR-{2000 + i}", f"2024-0{(i % 9) + 1}-01"))
    for i in range(150):
        conn.execute(
            "INSERT INTO claims VALUES (?, ?, ?)",
            (f"CL{7000 + i}", f"MBR-{2000 + (i % 45)}", 100.0 + i),
        )
    conn.commit()
    conn.close()
    return path


def test_sqlite_profile_and_relations(sqlite_db: Path):
    profile = profile_paths([sqlite_db])
    tables = {t["name"]: t for t in profile["tables"]}
    assert tables["warehouse/members"]["rows"] == 50
    assert tables["warehouse/claims"]["rows"] == 150
    cols = {c["name"]: c for c in tables["warehouse/members"]["columns"]}
    assert cols["member_id"]["uniqueness_ratio"] == 1.0
    assert any(
        r["from_table"] == "warehouse/claims" and r["to_table"] == "warehouse/members"
        for r in profile.get("relations", [])
    )
    outputs = json.dumps(profile) + render_markdown(profile)
    assert "MBR-" not in outputs and "CL70" not in outputs


def _write_csv(path: Path, rows: int, extra_col: bool = False, null_every: int = 0) -> None:
    with path.open("w", newline="") as fh:
        w = csv.writer(fh)
        header = ["id", "email"] + (["region"] if extra_col else [])
        w.writerow(header)
        for i in range(rows):
            email = "" if (null_every and i % null_every == 0) else f"u{i}@x.io"
            w.writerow([f"R{i:04d}", email] + (["west"] if extra_col else []))


def test_diff_detects_and_suppresses(tmp_path: Path):
    old_csv, new_csv = tmp_path / "old.csv", tmp_path / "new.csv"
    _write_csv(old_csv, 100)
    _write_csv(new_csv, 102, extra_col=True, null_every=4)  # +2 rows: below k, suppressed

    old_profile = profile_paths([old_csv])
    new_profile = profile_paths([new_csv])
    old_profile["tables"][0]["name"] = new_profile["tables"][0]["name"] = "data"

    diff = diff_profiles(old_profile, new_profile)
    table = diff["tables"][0]
    assert table["rows"]["delta"] == "+<5"  # k-suppressed, not "+2"
    assert table["columns_added"] == ["region"]
    email = next(c for c in table["columns_changed"] if c["name"] == "email")
    assert email["null_rate"]["new"] > email["null_rate"]["old"]


def test_diff_no_changes(tmp_path: Path):
    path = tmp_path / "same.csv"
    _write_csv(path, 60)
    profile = profile_paths([path])
    diff = diff_profiles(profile, profile)
    assert diff["tables"] == [] and not diff["tables_added"] and not diff["tables_removed"]
