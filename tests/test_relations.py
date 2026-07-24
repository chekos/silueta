from __future__ import annotations

import json
from pathlib import Path

from silueta.profiler import profile_paths
from silueta.report import render_markdown


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
