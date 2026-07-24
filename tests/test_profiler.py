import json
from pathlib import Path

from typer.testing import CliRunner

from silueta.cli import app
from silueta.profiler import profile_paths

runner = CliRunner()


def _columns(profile: dict) -> dict[str, dict]:
    return {c["name"]: c for c in profile["tables"][0]["columns"]}


def test_basic_profile(patients_csv: Path):
    profile = profile_paths([patients_csv])
    table = profile["tables"][0]
    assert table["rows"] == 30
    cols = _columns(profile)

    assert cols["mrn"]["uniqueness_ratio"] == 1.0
    assert cols["mrn"]["masks"][0]["mask"] == "AAA-999999"

    assert cols["clinic"]["constant"] is True
    assert "masks" not in cols["clinic"]
    assert "length" not in cols["clinic"]

    assert any(h["type"] == "email" for h in cols["email"]["semantic"])
    ssn_hits = [h for h in cols["ssn"]["semantic"] if h["type"] == "us_ssn"]
    assert ssn_hits and ssn_hits[0]["severity"] == "high"
    assert any(a["kind"] == "sensitive_us_ssn" for a in table["alerts"])

    assert cols["visit_date"]["temporal"]["year_span"] == [2025, 2025]
    assert cols["amount"]["numeric"]["magnitude_range"] == ["10^2", "10^2"]


def test_contract_field_present(patients_csv: Path):
    profile = profile_paths([patients_csv])
    assert "no raw cell values" in profile["silueta"]["contract"]


def test_small_table_suppression(tiny_csv: Path):
    profile = profile_paths([tiny_csv])
    table = profile["tables"][0]
    assert table["suppressed_small_table"] is True
    assert all(set(c) == {"name", "physical_type"} for c in table["columns"])


def test_cli_scan(patients_csv: Path, tmp_path: Path):
    out = tmp_path / "profile.json"
    report = tmp_path / "report.md"
    result = runner.invoke(app, ["scan", str(patients_csv), "--out", str(out), "--report", str(report)])
    assert result.exit_code == 0, result.output
    profile = json.loads(out.read_text())
    assert profile["tables"][0]["rows"] == 30
    assert report.read_text().startswith("# silueta profile")
