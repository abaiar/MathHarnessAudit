import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

import mathaudit.cli as cli_module
from mathaudit.cli import app

FIXTURES = Path(__file__).resolve().parents[1] / "examples" / "fixtures"


def invoke_ok(runner, args):
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    return result


def test_ingest_help_lists_every_builtin_adapter():
    result = CliRunner().invoke(app, ["ingest", "--help"])
    assert result.exit_code == 0, result.output
    for adapter in ("canonical", "icma", "mathgoal", "mathrouter", "otel"):
        assert adapter in result.output


def test_cli_end_to_end(tmp_path):
    runner = CliRunner()
    canonical = tmp_path / "canonical.jsonl"
    scored = tmp_path / "scored.jsonl"
    coverage = tmp_path / "coverage.json"
    audit = tmp_path / "audit.json"
    report_dir = tmp_path / "report"
    publication_dir = tmp_path / "publication"

    invoke_ok(
        runner,
        [
            "ingest",
            "--adapter",
            "icma",
            "--input",
            str(FIXTURES / "icma"),
            "--input-glob",
            "*.json",
            "--problems",
            str(FIXTURES / "problems.jsonl"),
            "--output",
            str(canonical),
            "--dataset-id",
            "fixture",
            "--stratum",
            "easy",
            "--run-id",
            "cli-test",
            "--system-id",
            "icma-fixture",
            "--system-name",
            "ICMA fixture",
            "--system-version",
            "synthetic",
            "--seed",
            "20260823",
        ],
    )
    assert canonical.exists()

    invoke_ok(runner, ["validate", str(canonical)])
    invoke_ok(runner, ["coverage", str(canonical), "--output", str(coverage)])
    invoke_ok(runner, ["score", str(canonical), "--output", str(scored)])
    invoke_ok(
        runner,
        [
            "publish",
            "--input",
            str(scored),
            "--config",
            str(FIXTURES / "publication_config.json"),
            "--output-dir",
            str(publication_dir),
        ],
    )
    invoke_ok(
        runner,
        [
            "audit",
            str(scored),
            "--source-a",
            "reasoner",
            "--source-b",
            "python_executor",
            "--bootstrap-replicates",
            "10",
            "--output",
            str(audit),
        ],
    )
    invoke_ok(
        runner,
        [
            "report",
            str(scored),
            "--output-dir",
            str(report_dir),
            "--pair",
            "reasoner,python_executor",
            "--bootstrap-replicates",
            "10",
        ],
    )

    assert json.loads(coverage.read_text(encoding="utf-8"))["episodes"] == 1
    assert "pairwise" in json.loads(audit.read_text(encoding="utf-8"))
    assert (report_dir / "report.json").exists()
    assert (report_dir / "manifest.json").exists()
    assert (report_dir / "index.html").exists()
    assert (publication_dir / "publication_manifest.json").exists()
    assert len(list((publication_dir / "figures").glob("*.svg"))) == 3


def test_cli_parquet_export(tmp_path):
    pytest.importorskip("pyarrow")
    runner = CliRunner()
    canonical = tmp_path / "canonical.jsonl"
    invoke_ok(
        runner,
        [
            "ingest",
            "--adapter",
            "icma",
            "--input",
            str(FIXTURES / "icma" / "0.json"),
            "--problems",
            str(FIXTURES / "problems.jsonl"),
            "--output",
            str(canonical),
            "--dataset-id",
            "fixture",
            "--stratum",
            "easy",
            "--run-id",
            "cli-parquet",
            "--system-id",
            "icma-fixture",
            "--system-name",
            "ICMA fixture",
            "--system-version",
            "synthetic",
        ],
    )
    output_dir = tmp_path / "parquet"
    invoke_ok(
        runner,
        ["export-parquet", str(canonical), "--output-dir", str(output_dir)],
    )
    assert len(list(output_dir.glob("*.parquet"))) == 7


def test_cli_rejects_invalid_report_pair(tmp_path, episode_factory):
    from mathaudit.io import write_episodes

    canonical = tmp_path / "canonical.jsonl"
    write_episodes(canonical, [episode_factory(0, True, True, True)])
    result = CliRunner().invoke(
        app,
        ["report", str(canonical), "--output-dir", str(tmp_path / "report"), "--pair", "a"],
    )
    assert result.exit_code != 0
    assert "pair must be source_a,source_b" in result.output


def test_cli_source_fingerprint_create_and_verify(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "entry.py").write_text("VALUE = 1\n", encoding="utf-8")
    (source / "runtime.lock").write_text("ignored\n", encoding="utf-8")
    manifest = tmp_path / "source-fingerprint.json"
    runner = CliRunner()
    invoke_ok(
        runner,
        [
            "fingerprint-source",
            str(source),
            "--system-id",
            "fixture",
            "--exclude-path",
            "runtime.lock",
            "--output",
            str(manifest),
        ],
    )
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["file_count"] == 1
    invoke_ok(
        runner,
        ["verify-source-fingerprint", str(source), "--manifest", str(manifest)],
    )


def test_cli_continuation_plan_verifier_forwards_source_lineage(tmp_path, monkeypatch):
    paths = {}
    for name in ("plan", "bundle", "authorization", "source-plan", "source-state"):
        path = tmp_path / (name + ".json")
        path.write_text(json.dumps({"name": name}), encoding="utf-8")
        paths[name] = path

    def verify(plan, bundle, authorization, *, source_plan, source_state):
        assert plan["name"] == "plan"
        assert bundle["name"] == "bundle"
        assert authorization["name"] == "authorization"
        assert source_plan["name"] == "source-plan"
        assert source_state["name"] == "source-state"
        return {"verified": True}

    monkeypatch.setattr(cli_module, "verify_qualification_execution_plan", verify)
    result = invoke_ok(
        CliRunner(),
        [
            "verify-qualification-plan",
            str(paths["plan"]),
            "--bundle-manifest",
            str(paths["bundle"]),
            "--authorization",
            str(paths["authorization"]),
            "--source-plan",
            str(paths["source-plan"]),
            "--source-state",
            str(paths["source-state"]),
        ],
    )
    assert json.loads(result.output)["verified"] is True

    incomplete = CliRunner().invoke(
        app,
        [
            "verify-qualification-plan",
            str(paths["plan"]),
            "--bundle-manifest",
            str(paths["bundle"]),
            "--authorization",
            str(paths["authorization"]),
            "--source-plan",
            str(paths["source-plan"]),
        ],
    )
    assert incomplete.exit_code != 0
    assert "must be supplied together" in incomplete.output


def test_cli_verifies_structural_and_semantic_compute_authorization(tmp_path):
    payload = json.loads(
        (FIXTURES / "compute_authorization_pending.json").read_text(encoding="utf-8")
    )
    payload.update(
        {
            "status": "authorized",
            "authorized_by": "fixture-owner",
            "authorized_at": "2026-08-23T00:00:00Z",
        }
    )
    payload["total_budget"].update(
        {
            "token_cap": 35_000_000,
            "currency": "CNY",
            "monetary_cap": 1000,
            "summed_wall_time_cap_s": 120_000,
        }
    )
    payload["monetary_accounting"].update(
        {
            "mode": "free_quota",
            "free_quota_confirmed": True,
            "evidence_source": "synthetic owner attestation",
        }
    )
    for system in payload["systems"]:
        system.update(
            {
                "provider": "fixture-provider",
                "model": "fixture-model",
                "endpoint_class": "managed-chat",
                "endpoint_url": "https://example.invalid/v1/chat/completions",
                "endpoint_available": True,
                "concurrency": 1,
                "max_output_tokens": 8192,
                "retry_policy": "transport-only once before response",
                "retry_control": {
                    "max_retries": 1,
                    "eligible_failure_class": "pre_response_transport_failure_only",
                    "forbid_after_any_response": True,
                    "forbid_on_parse_failure": True,
                    "forbid_on_tool_failure": True,
                },
                "token_cap": 10_000_000,
                "currency": "CNY",
                "monetary_cap": 300,
                "summed_wall_time_cap_s": 40_000,
            }
        )
    authorization = tmp_path / "authorization.json"
    authorization.write_text(json.dumps(payload), encoding="utf-8")
    schema = (
        Path(__file__).resolve().parents[1]
        / "schemas"
        / "mathaudit-compute-authorization-v0.1.schema.json"
    )
    result = invoke_ok(
        CliRunner(),
        [
            "verify-qualification-authorization",
            str(authorization),
            "--schema",
            str(schema),
        ],
    )
    assert "fixture-owner" not in result.output
    assert '"episode_cap": 150' in result.output
    ledger = tmp_path / "budget-ledger.json"
    ledger_result = invoke_ok(
        CliRunner(),
        [
            "initialize-qualification-ledger",
            "--authorization",
            str(authorization),
            "--output",
            str(ledger),
        ],
    )
    assert "fixture-owner" not in ledger_result.output
    assert json.loads(ledger.read_text(encoding="utf-8"))["requests"] == []


def test_cli_sample_and_json_schema_validation_are_end_to_end(tmp_path):
    source = tmp_path / "source.jsonl"
    source.write_text(
        "\n".join(
            json.dumps(
                {
                    "id": index,
                    "problem": "problem %d" % index,
                    "answer": "private %d" % index,
                    "level": 1 + index % 2,
                }
            )
            for index in range(6)
        )
        + "\n",
        encoding="utf-8",
    )
    private_output = tmp_path / "private.jsonl"
    manifest = tmp_path / "public.json"
    runner = CliRunner()
    invoke_ok(
        runner,
        [
            "sample",
            "--input",
            str(source),
            "--private-output",
            str(private_output),
            "--public-manifest",
            str(manifest),
            "--dataset-id",
            "fixture",
            "--stratum",
            "qualification",
            "--count",
            "4",
            "--id-field",
            "id",
            "--difficulty-field",
            "level",
            "--balance-field",
            "level",
        ],
    )
    public_text = manifest.read_text(encoding="utf-8").lower()
    assert "private " not in public_text
    assert len(private_output.read_text(encoding="utf-8").splitlines()) == 4
    invoke_ok(runner, ["verify-sample-manifest", str(manifest)])
    bundle_dir = tmp_path / "bundle"
    invoke_ok(
        runner,
        [
            "prepare-run-inputs",
            "--private-sample",
            str(private_output),
            "--public-manifest",
            str(manifest),
            "--output-dir",
            str(bundle_dir),
            "--system-id",
            "alpha",
            "--system-id",
            "beta",
        ],
    )
    invoke_ok(runner, ["verify-input-bundle", str(bundle_dir)])

    root = Path(__file__).resolve().parents[1]
    invoke_ok(
        runner,
        [
            "validate-json",
            str(root / "examples" / "fixtures" / "run_manifest.json"),
            "--schema",
            str(root / "schemas" / "mathaudit-run-manifest-v0.1.schema.json"),
        ],
    )
    invoke_ok(
        runner,
        [
            "validate-json",
            str(manifest),
            "--schema",
            str(root / "schemas" / "mathaudit-sample-manifest-v0.1.schema.json"),
        ],
    )
