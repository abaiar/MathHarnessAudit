import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from typer.testing import CliRunner

from mathaudit.adapters.canonical import CanonicalAdapter
from mathaudit.cli import app
from mathaudit.migration import migrate_episode_v1


def _schema(root, version):
    path = root / "schemas" / f"mathaudit-episode-v{version}.schema.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_episode_v01_to_v10_migration_is_lossless_and_schema_valid(episode_factory):
    root = Path(__file__).resolve().parents[1]
    legacy = episode_factory(0, True, False, True).model_dump(mode="json")
    legacy["schema_version"] = "0.1"
    migrated = migrate_episode_v1(legacy).model_dump(mode="json")

    assert migrated["schema_version"] == "1.0"
    assert {key: value for key, value in migrated.items() if key != "schema_version"} == {
        key: value for key, value in legacy.items() if key != "schema_version"
    }
    assert list(Draft202012Validator(_schema(root, "1.0")).iter_errors(migrated)) == []
    assert list(Draft202012Validator(_schema(root, "0.1")).iter_errors(migrated))


def test_episode_v10_migration_is_idempotent(episode_factory):
    current = episode_factory(0, True, False, True)
    assert current.schema_version == "1.0"
    assert migrate_episode_v1(current).model_dump(mode="json") == current.model_dump(mode="json")


def test_episode_migration_rejects_unknown_version(episode_factory):
    payload = episode_factory(0, True, False, True).model_dump(mode="json")
    payload["schema_version"] = "2.0"
    with pytest.raises(ValueError, match="schema_version"):
        migrate_episode_v1(payload)


def test_canonical_adapter_accepts_legacy_and_stable_versions(episode_factory):
    adapter = CanonicalAdapter()
    payload = episode_factory(0, True, False, True).model_dump(mode="json")
    assert adapter.can_handle(payload)
    payload["schema_version"] = "0.1"
    assert adapter.can_handle(payload)
    payload["schema_version"] = "2.0"
    assert not adapter.can_handle(payload)


def test_cli_migrates_jsonl_and_refuses_overwrite(tmp_path, episode_factory):
    legacy = episode_factory(0, True, False, True).model_dump(mode="json")
    legacy["schema_version"] = "0.1"
    source = tmp_path / "legacy.jsonl"
    source.write_text(json.dumps(legacy) + "\n", encoding="utf-8")
    output = tmp_path / "stable.jsonl"
    runner = CliRunner()

    result = runner.invoke(app, ["migrate-episode-v1", str(source), "--output", str(output)])
    assert result.exit_code == 0, result.output
    migrated = json.loads(output.read_text(encoding="utf-8"))
    assert migrated["schema_version"] == "1.0"

    second = runner.invoke(app, ["migrate-episode-v1", str(source), "--output", str(output)])
    assert second.exit_code == 1
    assert "output already exists" in second.output


def test_v1_compatibility_record_covers_every_public_v01_fixture():
    root = Path(__file__).resolve().parents[1]
    record = json.loads(
        (root / "schemas" / "mathaudit-v1-compatibility.json").read_text(encoding="utf-8")
    )
    entries = record["retained_historical_formats"]
    assert {entry["fixture"] for entry in entries} == {
        "examples/fixtures/compute_authorization_pending.json",
        "examples/fixtures/publication_config.json",
        "examples/fixtures/run_manifest.json",
        "examples/fixtures/sample_manifest.json",
    }
    for entry in entries:
        payload = json.loads((root / entry["fixture"]).read_text(encoding="utf-8"))
        assert payload["format"] == entry["format"]
        assert entry["strategy"] == "accepted_unchanged"
