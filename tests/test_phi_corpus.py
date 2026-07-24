"""Synthetic PHI corpus: checksum-valid generated identifiers, zero real data.

Tests issues #5 (int-coded columns) and #6 (validator depth) — detection must
work on generated NPI/DEA/SSN/ICD values and on identifiers sniffed as ints.
"""

from __future__ import annotations

import json
from pathlib import Path

from conftest import make_dea, make_npi
from silueta.profiler import profile_paths
from silueta.report import render_markdown
from silueta.semantic import is_dea, is_npi


def test_generators_are_valid():
    assert all(is_npi(make_npi(i)) for i in range(50))
    assert all(is_dea(make_dea(i)) for i in range(50))




def _cols(profile: dict) -> dict[str, dict]:
    return {c["name"]: c for c in profile["tables"][0]["columns"]}


def test_phi_detection(phi_csv: Path):
    profile = profile_paths([phi_csv])
    cols = _cols(profile)

    mrn = cols["mrn"]
    assert any(h["type"] == "mrn_like" and h["basis"] == "name+shape" for h in mrn["semantic"])
    assert "sensitive_mrn_like" in mrn["alerts"]

    npi = cols["provider_npi"]  # sniffed as BIGINT — int-code path must recover shape
    assert npi["masks"][0]["mask"] == "9999999999"
    assert any(h["type"] == "us_healthcare_npi" and h["match_rate"] == 1.0 for h in npi["semantic"])

    dea = cols["dea_number"]
    assert any(h["type"] == "us_dea_number" and h["severity"] == "high" for h in dea["semantic"])

    assert any(h["type"] == "icd10_shape" for h in cols["dx_code"]["semantic"])

    dob = cols["dob"]
    assert "dob" in dob["name_signals"]
    assert "sensitive_dob" in dob["alerts"]
    assert dob["temporal"]["year_span"] == [1950, 1989]

    zip_col = cols["zip"]
    assert "possible_leading_zero_loss" in zip_col["alerts"]
    assert zip_col["masks"][0]["mask"] == "9999"

    seen = cols["seen_on"]
    assert any(h["type"] == "us_date" for h in seen["semantic"])


def test_phi_corpus_contract(phi_csv: Path):
    profile = profile_paths([phi_csv])
    outputs = json.dumps(profile) + render_markdown(profile)
    for fragment in ("MR8000", "BQ100", make_npi(0), "1950-06-15"):
        assert fragment not in outputs, f"leaked: {fragment}"
