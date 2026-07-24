from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from conftest import EMAILS, MRNS, PATIENT_NAMES, SSNS
from silueta.cli import app
from silueta.emit import emit_dbt_sources, emit_dbt_staging, emit_snowflake, snake
from silueta.profiler import profile_paths

runner = CliRunner()


def test_snake():
    assert snake("Provider NPI") == "provider_npi"
    assert snake("Claim ID") == "claim_id"
    assert snake("memberId") == "member_id"


def test_emitters_end_to_end(phi_csv: Path):
    profile = profile_paths([phi_csv])
    table = profile["tables"][0]

    ddl = emit_snowflake(profile)
    # zip lost leading zeros -> lands as VARCHAR, not NUMBER
    assert "ZIP" in ddl and "NUMBER" in ddl
    zip_line = next(line for line in ddl.splitlines() if line.strip().startswith("ZIP"))
    assert "VARCHAR" in zip_line and "leading zeros" in zip_line

    sources = emit_dbt_sources(profile)
    assert "- name: mrn" in sources
    assert "unique" in sources and "not_null" in sources
    assert "masking-policy candidate" in sources
    assert "accepted_values" not in sources.replace("# TODO accepted_values", "")

    staging = emit_dbt_staging(table)
    assert "LPAD(ZIP, 5, '0') as zip" in staging
    assert "TRY_TO_DATE(SEEN_ON, 'MM/DD/YYYY')" in staging


def test_relationship_test_emitted(linked_csvs: list[Path]):
    profile = profile_paths(linked_csvs)
    sources = emit_dbt_sources(profile)
    assert "relationships:" in sources
    assert "to: source('vendor', 'members')" in sources
    assert "field: member_id" in sources


def test_emitted_artifacts_honor_contract(patients_csv: Path, tmp_path: Path):
    out = tmp_path / "profile.json"
    result = runner.invoke(app, ["scan", str(patients_csv), "--out", str(out)])
    assert result.exit_code == 0, result.output

    gen = tmp_path / "gen"
    for target in ("dbt", "snowflake"):
        result = runner.invoke(app, ["emit", target, str(out), "--out-dir", str(gen)])
        assert result.exit_code == 0, result.output

    emitted = "".join(p.read_text() for p in gen.iterdir())
    leaked = [v for v in (*PATIENT_NAMES, *EMAILS, *SSNS, *MRNS) if v in emitted]
    assert not leaked, leaked
    for fragment in ("Zqxv", "sentinel-example"):
        assert fragment not in emitted
