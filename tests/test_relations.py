from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from silueta.profiler import profile_paths
from silueta.report import render_markdown


@pytest.fixture()
def linked_csvs(tmp_path: Path) -> list[Path]:
    members = tmp_path / "members.csv"
    with members.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["member_id", "tier"])
        for i in range(60):
            w.writerow([f"MBR-{1000 + i}", ["gold", "silver", "bronze"][i % 3]])

    claims = tmp_path / "claims.csv"
    with claims.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["claim_id", "member_id", "status"])
        for i in range(120):
            w.writerow([f"C{9000 + i}", f"MBR-{1000 + (i % 40)}", ["OPEN", "PAID", "DENIED"][i % 3]])

    return [members, claims]


def test_fk_candidate_detected(linked_csvs: list[Path]):
    profile = profile_paths(linked_csvs)
    relations = profile.get("relations", [])
    assert any(
        r["from_table"] == "claims"
        and r["from_column"] == "member_id"
        and r["to_table"] == "members"
        and r["to_column"] == "member_id"
        and r["containment"] == 1.0
        and r["name_similarity"] > 0.5
        for r in relations
    ), relations


def test_enums_do_not_dominate(linked_csvs: list[Path]):
    profile = profile_paths(linked_csvs)
    for rel in profile.get("relations", []):
        # status/tier are low-cardinality enums: the floor must exclude them.
        assert rel["from_column"] not in ("status", "tier")
        assert rel["to_column"] not in ("status", "tier")


def test_relations_carry_no_values(linked_csvs: list[Path]):
    profile = profile_paths(linked_csvs)
    outputs = json.dumps(profile.get("relations", [])) + render_markdown(profile)
    assert "MBR-" not in outputs and "C90" not in outputs
