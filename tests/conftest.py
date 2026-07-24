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


@pytest.fixture()
def tiny_csv(tmp_path: Path) -> Path:
    path = tmp_path / "lookup.csv"
    path.write_text("code,label\nA,Zqxvalpha\nB,Zqxvbeta\nC,Zqxvgamma\n")
    return path
