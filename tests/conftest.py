from __future__ import annotations

import csv
from pathlib import Path

import pytest

# Distinctive sentinel values: none of these strings may ever appear in a profile.
PATIENT_NAMES = [f"Zqxvpatient{i} Wqzlast{i}" for i in range(30)]
EMAILS = [f"zqxv.user{i}@sentinel-example.org" for i in range(30)]
SSNS = [f"52{i % 10}-4{i % 10}-{1000 + i}" for i in range(30)]
MRNS = [f"MRN-{700000 + i}" for i in range(30)]


@pytest.fixture()
def patients_csv(tmp_path: Path) -> Path:
    path = tmp_path / "patients.csv"
    with path.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["mrn", "full_name", "email", "ssn", "visit_date", "amount", "clinic"])
        for i in range(30):
            writer.writerow(
                [
                    MRNS[i],
                    PATIENT_NAMES[i],
                    EMAILS[i],
                    SSNS[i],
                    f"2025-0{(i % 9) + 1}-15",
                    f"{100 + i}.50",
                    "NORTHSIDE",  # constant column
                ]
            )
    return path


def make_npi(seed: int) -> str:
    """Generate a checksum-valid NPI from a 9-digit seed."""
    from silueta.semantic import luhn_valid

    base = f"{100000000 + seed}"[:9]
    for check in range(10):
        if luhn_valid("80840" + base + str(check)):
            return base + str(check)
    raise AssertionError("unreachable")


def make_dea(seed: int) -> str:
    digits = [int(ch) for ch in f"{1000000 + seed}"[:6]]
    check = ((digits[0] + digits[2] + digits[4]) + 2 * (digits[1] + digits[3] + digits[5])) % 10
    return "BQ" + "".join(map(str, digits)) + str(check)


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
                    f"{2010 + i % 60:04d}",
                    f"11/{(i % 28) + 1}/2025",
                ]
            )
    return path


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


@pytest.fixture()
def tiny_csv(tmp_path: Path) -> Path:
    path = tmp_path / "lookup.csv"
    path.write_text("code,label\nA,Zqxvalpha\nB,Zqxvbeta\nC,Zqxvgamma\n")
    return path
