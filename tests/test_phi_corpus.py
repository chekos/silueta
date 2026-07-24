"""Synthetic PHI corpus: checksum-valid generated identifiers, zero real data.

Tests issues #5 (int-coded columns) and #6 (validator depth) — detection must
work on generated NPI/DEA/SSN/ICD values and on identifiers sniffed as ints.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from silueta.profiler import profile_paths
from silueta.report import render_markdown
from silueta.semantic import is_dea, is_npi, luhn_valid


def make_npi(seed: int) -> str:
    """Generate a checksum-valid NPI from a 9-digit seed."""
    base = f"{100000000 + seed}"[:9]
    for check in range(10):
        if luhn_valid("80840" + base + str(check)):
            return base + str(check)
    raise AssertionError("unreachable")


def make_dea(seed: int) -> str:
    digits = [int(ch) for ch in f"{1000000 + seed}"[:6]]
    check = ((digits[0] + digits[2] + digits[4]) + 2 * (digits[1] + digits[3] + digits[5])) % 10
    return "BQ" + "".join(map(str, digits)) + str(check)


def test_generators_are_valid():
    assert all(is_npi(make_npi(i)) for i in range(50))
    assert all(is_dea(make_dea(i)) for i in range(50))


@pytest.fixture()
def phi_csv(tmp_path: Path) -> Path:
    path = tmp_path / "encounters.csv"
    icd_codes = ["E11.9", "I10", "J45.909", "M54.5", "F32.9", "K21.0"]
    with path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["mrn", "provider_npi", "dea_number", "dx_code", "dob", "zip", "seen_on"])
        for i in range(40):
            w.writerow(
                [
                    f"MR{800000 + i}",
                    make_npi(i * 7),
                    make_dea(i * 3),
                    icd_codes[i % len(icd_codes)],
                    f"19{50 + (i % 40):02d}-06-15",
                    f"{2010 + i % 60:04d}",  # 4-digit zips: leading zero lost upstream
                    f"11/{(i % 28) + 1}/2025",
                ]
            )
    return path


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
