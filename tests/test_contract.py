"""The contract test: no cell value from the source may appear in any output.

This is the regression suite the README points to — the trust story is that
this corpus-driven check gates every change, not a user-facing canary button.
"""

import json
from pathlib import Path

from conftest import EMAILS, MRNS, PATIENT_NAMES, SSNS
from silueta.profiler import profile_paths
from silueta.report import render_markdown


def test_no_cell_values_in_outputs(patients_csv: Path):
    profile = profile_paths([patients_csv])
    outputs = json.dumps(profile) + render_markdown(profile)

    leaked = [
        value
        for value in (*PATIENT_NAMES, *EMAILS, *SSNS, *MRNS)
        if value in outputs
    ]
    assert not leaked, f"raw cell values leaked into profile output: {leaked[:5]}"

    # Distinctive fragments must not survive either (name stems, email domain).
    for fragment in ("Zqxv", "Wqzlast", "sentinel-example"):
        assert fragment not in outputs, f"value fragment leaked: {fragment}"


def test_tiny_table_leaks_nothing_but_structure(tiny_csv: Path):
    profile = profile_paths([tiny_csv])
    outputs = json.dumps(profile) + render_markdown(profile)
    assert "Zqxv" not in outputs
