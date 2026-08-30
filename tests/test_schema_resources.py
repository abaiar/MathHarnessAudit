# SPDX-License-Identifier: MIT

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from mathaudit.cli import app
from mathaudit.schema_resources import export_schemas, read_schema_text, schema_names

ROOT = Path(__file__).resolve().parents[1]


def test_embedded_schemas_match_the_public_source_directory(tmp_path: Path) -> None:
    expected = sorted(path.name for path in (ROOT / "schemas").glob("*.json"))
    assert list(schema_names()) == expected
    assert len(expected) == 41
    for name in expected:
        assert read_schema_text(name) == (ROOT / "schemas" / name).read_text(encoding="utf-8")

    exported = export_schemas(tmp_path / "exported")
    assert [path.name for path in exported] == expected
    for path in exported:
        assert path.read_text(encoding="utf-8") == (ROOT / "schemas" / path.name).read_text(
            encoding="utf-8"
        )


def test_schema_resource_rejects_unknown_names_and_nonempty_output(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown MathHarnessAudit schema"):
        read_schema_text("../private.json")
    destination = tmp_path / "existing"
    destination.mkdir()
    (destination / "keep.txt").write_text("keep", encoding="utf-8")
    with pytest.raises(FileExistsError, match="must be empty"):
        export_schemas(destination)


def test_schema_cli_lists_and_exports_embedded_resources(tmp_path: Path) -> None:
    runner = CliRunner()
    listed = runner.invoke(app, ["list-schemas"])
    assert listed.exit_code == 0
    assert "mathaudit-episode-v1.0.schema.json" in listed.stdout

    destination = tmp_path / "cli-export"
    exported = runner.invoke(app, ["export-schemas", "--output-dir", str(destination)])
    assert exported.exit_code == 0
    assert "Exported 41 JSON Schemas" in exported.stdout
    assert len(list(destination.glob("*.json"))) == 41
