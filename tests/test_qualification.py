import copy
import importlib.metadata
import json
import platform
import re
import sys
from pathlib import Path

import pytest

from mathaudit.fingerprint import fingerprint_source_tree
from mathaudit.hashing import sha256_json, sha256_text
from mathaudit.qualification import (
    _verify_reference_environment,
    prepare_qualification_run_manifests,
    qualification_authorization_issues,
    run_qualification_preflight,
    verify_qualification_authorization,
)
from mathaudit.runprep import prepare_matched_run_inputs
from mathaudit.sampling import public_sample_manifest, select_sample


def _authorized():
    systems = []
    for system_id in ("mathrouter", "icma", "mathgoal"):
        systems.append(
            {
                "system_id": system_id,
                "provider": "registered-provider",
                "model": "registered-model",
                "model_revision": None,
                "endpoint_class": "managed-chat-endpoint",
                "endpoint_url": "https://example.invalid/v1/chat/completions",
                "endpoint_available": True,
                "parameters": {"temperature": 0},
                "concurrency": 1,
                "episode_timeout_s": 1200,
                "max_output_tokens": 8192,
                "retry_policy": "transport-only once before response",
                "retry_control": {
                    "max_retries": 1,
                    "eligible_failure_class": "pre_response_transport_failure_only",
                    "forbid_after_any_response": True,
                    "forbid_on_parse_failure": True,
                    "forbid_on_tool_failure": True,
                },
                "episode_cap": 50,
                "token_cap": 10_000_000,
                "currency": "CNY",
                "monetary_cap": 300,
                "summed_wall_time_cap_s": 40_000,
            }
        )
    return {
        "format": "mathaudit-compute-authorization-v0.1",
        "authorization_id": "fixture-q",
        "status": "authorized",
        "scope": "qualification_q",
        "authorized_by": "owner",
        "authorized_at": "2026-08-23T00:00:00Z",
        "total_budget": {
            "episode_cap": 150,
            "token_cap": 35_000_000,
            "currency": "CNY",
            "monetary_cap": 1000,
            "summed_wall_time_cap_s": 120000,
        },
        "monetary_accounting": {
            "mode": "free_quota",
            "free_quota_confirmed": True,
            "input_cny_per_million_tokens": None,
            "output_cny_per_million_tokens": None,
            "evidence_source": "synthetic owner attestation",
        },
        "stop_policy": {
            "quota_or_transport_failure_rate": 0.05,
            "stop_on_task_dependent_missingness": True,
            "stop_on_trace_loss": True,
        },
        "systems": systems,
        "secrets_recorded": False,
        "notes": [],
    }


def test_authorized_record_passes_and_summary_is_redacted():
    payload = _authorized()
    assert qualification_authorization_issues(payload) == []
    summary = verify_qualification_authorization(payload)
    assert summary["episode_cap"] == 150
    assert summary["system_ids"] == ["icma", "mathgoal", "mathrouter"]
    assert "endpoint" not in summary


def test_continuation_authorization_uses_exact_suffix_caps():
    payload = _authorized()
    payload["format"] = "mathaudit-compute-authorization-v0.2"
    payload["authorization_id"] = "fixture-q-continuation"
    payload["total_budget"]["episode_cap"] = 139
    caps = {"mathrouter": 46, "icma": 46, "mathgoal": 47}
    for system in payload["systems"]:
        system["episode_cap"] = caps[system["system_id"]]
        system["parameters"]["gateway_upstream_timeout_s"] = 150
        if system["system_id"] == "mathgoal":
            system["parameters"]["gateway_pre_response_transport_retries"] = 1
            system["parameters"]["llm_timeout_seconds"] = 315
    payload["continuation"] = {
        "source_authorization_id": "fixture-q",
        "source_plan_sha256": "a" * 64,
        "source_state_sha256": "b" * 64,
        "source_closeout_sha256": "c" * 64,
        "completed_prefix_episode_count": 11,
        "restart_sequence": 11,
        "final_target_episode_count": 150,
    }
    assert qualification_authorization_issues(payload) == []
    assert verify_qualification_authorization(payload)["episode_cap"] == 139

    payload["systems"][0]["episode_cap"] -= 1
    issues = qualification_authorization_issues(payload)
    assert any("system episode caps" in issue for issue in issues)


def test_skip_boundary_authorization_defers_one_replacement_slot():
    payload = _authorized()
    payload["format"] = "mathaudit-compute-authorization-v0.3"
    payload["authorization_id"] = "fixture-q-skip-boundary"
    payload["total_budget"]["episode_cap"] = 68
    caps = {"mathrouter": 23, "icma": 23, "mathgoal": 22}
    for system in payload["systems"]:
        system["episode_cap"] = caps[system["system_id"]]
        system["parameters"]["gateway_upstream_timeout_s"] = 180
        if system["system_id"] == "mathgoal":
            system["parameters"]["gateway_pre_response_transport_retries"] = 1
            system["parameters"]["llm_timeout_seconds"] = 400
    payload["continuation"] = {
        "source_authorization_id": "fixture-q-continuation",
        "source_plan_sha256": "a" * 64,
        "source_state_sha256": "b" * 64,
        "source_closeout_sha256": "c" * 64,
        "completed_prefix_episode_count": 81,
        "restart_sequence": 82,
        "final_target_episode_count": 150,
        "deferred_replacement_count": 1,
        "deferred_replacement_sequence": 81,
    }
    assert qualification_authorization_issues(payload) == []
    assert verify_qualification_authorization(payload)["episode_cap"] == 68
    payload["continuation"]["deferred_replacement_count"] = 0
    assert any("defer exactly one" in issue for issue in qualification_authorization_issues(payload))


def test_pending_or_incomplete_record_cannot_authorize_compute():
    payload = _authorized()
    payload["status"] = "pending"
    payload["total_budget"]["token_cap"] = None
    payload["systems"][0]["endpoint_available"] = None
    issues = qualification_authorization_issues(payload)
    assert any("not authorized" in issue for issue in issues)
    assert any("token_cap" in issue for issue in issues)
    assert any("availability" in issue for issue in issues)
    with pytest.raises(ValueError, match="not runnable"):
        verify_qualification_authorization(payload)


def test_empty_record_reports_all_top_level_control_families():
    issues = qualification_authorization_issues({})
    assert any("format" in issue for issue in issues)
    assert any("scope" in issue for issue in issues)
    assert any("authorizing" in issue for issue in issues)
    assert any("secrets_recorded" in issue for issue in issues)
    assert any("total_budget" in issue for issue in issues)
    assert any("stop_policy" in issue for issue in issues)
    assert any("systems" in issue for issue in issues)


def test_nested_policy_types_and_missing_runtime_fields_are_rejected():
    payload = _authorized()
    payload["total_budget"].update(
        {"episode_cap": 149, "token_cap": True, "currency": "yuan", "monetary_cap": True}
    )
    payload["stop_policy"] = {
        "quota_or_transport_failure_rate": 0,
        "stop_on_task_dependent_missingness": False,
        "stop_on_trace_loss": False,
    }
    payload["systems"][0]["provider"] = None
    payload["systems"][0]["parameters"] = None
    payload["systems"][0]["episode_timeout_s"] = 0
    payload["systems"][0]["max_output_tokens"] = -1
    issues = qualification_authorization_issues(payload)
    assert any("episode_cap" in issue for issue in issues)
    assert any("currency" in issue for issue in issues)
    assert any("monetary_cap" in issue for issue in issues)
    assert any("stop rate" in issue for issue in issues)
    assert any("trace loss" in issue for issue in issues)
    assert any("provider" in issue for issue in issues)
    assert any("parameters" in issue for issue in issues)


def test_nonobject_system_entry_is_rejected_without_crashing():
    payload = _authorized()
    payload["systems"] = ["not-an-object"]
    issues = qualification_authorization_issues(payload)
    assert any("exactly once" in issue for issue in issues)
    assert any("must be an object" in issue for issue in issues)


def test_record_rejects_duplicate_system_and_credential_bearing_endpoint():
    payload = _authorized()
    payload["systems"][2] = copy.deepcopy(payload["systems"][1])
    payload["systems"][0]["endpoint_class"] = "https://host/?api_key=secret-value"
    issues = qualification_authorization_issues(payload)
    assert any("exactly once" in issue for issue in issues)
    assert any("credential" in issue for issue in issues)


def test_per_system_caps_cannot_exceed_total_authorization():
    payload = _authorized()
    payload["systems"][0]["token_cap"] = payload["total_budget"]["token_cap"]
    payload["systems"][0]["monetary_cap"] = payload["total_budget"]["monetary_cap"]
    payload["systems"][0]["summed_wall_time_cap_s"] = payload["total_budget"][
        "summed_wall_time_cap_s"
    ]
    payload["systems"][1]["currency"] = "USD"
    issues = qualification_authorization_issues(payload)
    assert any("token caps exceed" in issue for issue in issues)
    assert any("monetary caps exceed" in issue for issue in issues)
    assert any("wall-time caps exceed" in issue for issue in issues)
    assert any("currency must match" in issue for issue in issues)


def test_total_wall_cap_and_retry_semantics_are_fail_closed():
    payload = _authorized()
    payload["total_budget"]["summed_wall_time_cap_s"] = True
    payload["systems"][0]["retry_control"]["forbid_on_parse_failure"] = False
    issues = qualification_authorization_issues(payload)
    assert any("total summed_wall_time_cap_s" in issue for issue in issues)
    assert any("retry_control" in issue for issue in issues)


def test_monetary_accounting_requires_evidence_and_valid_mode_values():
    payload = _authorized()
    payload["monetary_accounting"] = {
        "mode": "free_quota",
        "free_quota_confirmed": False,
        "input_cny_per_million_tokens": 1,
        "output_cny_per_million_tokens": None,
        "evidence_source": "",
    }
    issues = qualification_authorization_issues(payload)
    assert any("evidence_source" in issue for issue in issues)
    assert any("explicit confirmation" in issue for issue in issues)
    assert any("positive token rates" in issue for issue in issues)

    payload = _authorized()
    payload["monetary_accounting"] = {
        "mode": "token_tariff",
        "free_quota_confirmed": False,
        "input_cny_per_million_tokens": -1,
        "output_cny_per_million_tokens": None,
        "evidence_source": "fixture tariff",
    }
    issues = qualification_authorization_issues(payload)
    assert sum("must be nonnegative" in issue for issue in issues) == 2


def test_reference_environment_snapshot_verifier_is_exact(tmp_path):
    rows = sorted(
        {
            re.sub(r"[-_.]+", "-", distribution.metadata["Name"]).lower()
            + "=="
            + distribution.version
            for distribution in importlib.metadata.distributions()
            if distribution.metadata.get("Name")
        }
    )
    snapshot = tmp_path / "environment.freeze.txt"
    snapshot.write_text("\n".join(rows) + "\n", encoding="utf-8")
    detail = _verify_reference_environment(
        Path(sys.executable), snapshot, platform.python_version()
    )
    assert platform.python_version() in detail
    snapshot.write_text(snapshot.read_text(encoding="utf-8") + "fake==1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="snapshot drift"):
        _verify_reference_environment(Path(sys.executable), snapshot, platform.python_version())


@pytest.mark.parametrize("value", [True, 0, -1, 1.5, None])
def test_positive_integer_runtime_fields_reject_bool_and_nonintegers(value):
    payload = _authorized()
    payload["systems"][0]["concurrency"] = value
    assert any("concurrency" in issue for issue in qualification_authorization_issues(payload))


def test_full_provider_free_preflight_passes_then_detects_lock_drift(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    lock = tmp_path / "uv.lock"
    lock.write_bytes(b"frozen-lock\n")
    lock_hash = sha256_text("frozen-lock\n")

    records = [
        {
            "id": index,
            "problem": "Compute %d+1." % index,
            "answer": str(index + 1),
            "level": 1,
        }
        for index in range(50)
    ]
    selected, diagnostics = select_sample(
        records,
        dataset_id="fixture",
        count=50,
        seed=9,
        statement_field="problem",
        id_field="id",
        difficulty_field="level",
    )
    selection_config = {
        "count": 50,
        "statement_field": "problem",
        "id_field": "id",
        "difficulty_field": "level",
        "difficulty_gt": None,
        "difficulty_le": None,
        "balance_field": None,
        "balance_depth": None,
        "balance_mode": "equal",
        "duplicate_problem_policy": "exclude_all_records_in_duplicate_problem_groups",
    }
    source_path = tmp_path / "source.jsonl"
    source_path.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8"
    )
    sample_manifest = public_sample_manifest(
        selected,
        source_path=source_path,
        dataset_id="fixture",
        dataset_version="v1",
        stratum="qualification",
        seed=9,
        selection_config=selection_config,
        diagnostics=diagnostics,
    )
    sample_path = tmp_path / "sample.json"
    sample_path.write_text(json.dumps(sample_manifest), encoding="utf-8")
    private_records = []
    for item in selected:
        private_record = dict(item.record)
        private_record["_mathaudit"] = {
            "problem_sha256": item.problem_hash,
            "record_sha256": item.record_hash,
            "balance_group": item.balance_group,
        }
        private_records.append(private_record)
    private_path = tmp_path / "private.jsonl"
    private_path.write_text(
        "\n".join(json.dumps(record) for record in private_records) + "\n",
        encoding="utf-8",
    )
    bundle_dir = tmp_path / "bundle"
    bundle = prepare_matched_run_inputs(
        private_samples=[private_path],
        public_manifests=[sample_path],
        output_dir=bundle_dir,
        system_ids=["mathrouter", "icma", "mathgoal"],
        schedule_seed=9,
    )

    source_specs = []
    for system_id in ("mathrouter", "icma", "mathgoal"):
        source = tmp_path / (system_id + "-source")
        source.mkdir()
        (source / "entry.py").write_text("VALUE = 1\n", encoding="utf-8")
        fingerprint = fingerprint_source_tree(source, system_id=system_id)
        fingerprint_path = tmp_path / (system_id + "-fingerprint.json")
        fingerprint_path.write_text(json.dumps(fingerprint), encoding="utf-8")
        spec = {
            "system_id": system_id,
            "kind": "fingerprint",
            "path": str(source),
            "manifest": str(fingerprint_path),
            "run_source_fingerprint": fingerprint["manifest_sha256"],
            "name": system_id,
            "version": "fixture",
            "adapter_name": system_id,
            "adapter_version": "0.1",
            "adapter_fidelity": "A",
        }
        if system_id == "mathrouter":
            spec.update(
                {
                    "kind": "git",
                    "expected_commit": "a" * 40,
                    "require_clean": True,
                    "critical_files": [
                        {
                            "path": "entry.py",
                            "sha256": fingerprint["files"][0]["sha256"],
                        }
                    ],
                }
            )
        source_specs.append(spec)

    def fake_git(_root, *arguments):
        return "a" * 40 if arguments[:2] == ("rev-parse", "HEAD") else ""

    monkeypatch.setattr("mathaudit.qualification._run_git", fake_git)

    authorization = _authorized()
    authorization_path = tmp_path / "authorization.json"
    authorization_path.write_text(json.dumps(authorization), encoding="utf-8")
    required = tmp_path / "runner.py"
    required.write_bytes(b"# frozen runner\n")
    config = {
        "format": "mathaudit-qualification-preflight-v0.1",
        "workspace_root": ".",
        "expected_system_ids": ["mathrouter", "icma", "mathgoal"],
        "dependency_lock": {"path": str(lock), "expected_sha256": lock_hash},
        "authorization": {
            "path": str(authorization_path),
            "schema": str(root / "schemas" / "mathaudit-compute-authorization-v0.1.schema.json"),
        },
        "sources": source_specs,
        "sample_manifests": [
            {
                "path": str(sample_path),
                "expected_manifest_sha256": sample_manifest["manifest_sha256"],
            }
        ],
        "input_bundle": {
            "path": str(bundle_dir),
            "expected_task_count": 50,
            "expected_bundle_sha256": bundle["bundle_sha256"],
        },
        "required_artifacts": [
            {
                "artifact_id": "runner",
                "path": str(required),
                "expected_sha256": sha256_text("# frozen runner\n"),
            }
        ],
        "run_manifest_schema": str(root / "schemas" / "mathaudit-run-manifest-v0.1.schema.json"),
        "run_manifests": [
            {
                "system_id": system_id,
                "path": str(tmp_path / "runs" / (system_id + ".json")),
            }
            for system_id in ("mathrouter", "icma", "mathgoal")
        ],
    }
    config_path = tmp_path / "preflight.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    preparation = prepare_qualification_run_manifests(
        config_path, authorization_path, tmp_path / "runs"
    )
    assert preparation["authorization_id"] == authorization["authorization_id"]
    assert len(preparation["files"]) == 4
    generated_runtime = json.loads(
        (tmp_path / "runs" / "mathrouter.json").read_text(encoding="utf-8")
    )["runtime"]
    expected_runtime = authorization["systems"][0]
    for key in (
        "provider",
        "model",
        "model_revision",
        "endpoint_class",
        "endpoint_url",
        "parameters",
        "episode_timeout_s",
        "concurrency",
        "max_output_tokens",
        "retry_policy",
        "retry_control",
    ):
        assert generated_runtime[key] == expected_runtime[key]
    with pytest.raises(FileExistsError):
        prepare_qualification_run_manifests(
            config_path, authorization_path, tmp_path / "runs"
        )
    report = run_qualification_preflight(config_path, environment={})
    assert report["ready"] is True, report
    assert report["fail_count"] == 0
    assert report["report_sha256"] == sha256_json(
        {key: value for key, value in report.items() if key != "report_sha256"}
    )

    lock.write_bytes(b"drifted\n")
    drift = run_qualification_preflight(config_path, environment={})
    assert drift["ready"] is False
    assert any(
        item["check_id"] == "dependency_lock" and item["status"] == "fail"
        for item in drift["checks"]
    )
