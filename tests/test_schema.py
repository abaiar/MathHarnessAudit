# SPDX-License-Identifier: MIT

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from mathaudit.execution import compile_qualification_execution_plan
from mathaudit.fingerprint import fingerprint_source_tree
from mathaudit.hashing import sha256_json
from mathaudit.models import Episode
from mathaudit.sampling import verify_sample_manifest_hash

SCHEMA_PATH = (
    Path(__file__).resolve().parents[1] / "schemas" / "mathaudit-episode-v0.1.schema.json"
)
EPISODE_V10_SCHEMA_PATH = SCHEMA_PATH.with_name("mathaudit-episode-v1.0.schema.json")
RUN_SCHEMA_PATH = SCHEMA_PATH.with_name("mathaudit-run-manifest-v0.1.schema.json")
DEVIATION_SCHEMA_PATH = SCHEMA_PATH.with_name("mathaudit-deviation-event-v0.1.schema.json")
SAMPLE_SCHEMA_PATH = SCHEMA_PATH.with_name("mathaudit-sample-manifest-v0.1.schema.json")
PUBLICATION_SCHEMA_PATH = SCHEMA_PATH.with_name(
    "mathaudit-publication-config-v0.1.schema.json"
)
SOURCE_FINGERPRINT_SCHEMA_PATH = SCHEMA_PATH.with_name(
    "mathaudit-source-fingerprint-v0.1.schema.json"
)
COMPUTE_AUTHORIZATION_SCHEMA_PATH = SCHEMA_PATH.with_name(
    "mathaudit-compute-authorization-v0.1.schema.json"
)
EXECUTION_PLAN_SCHEMA_PATH = SCHEMA_PATH.with_name(
    "mathaudit-qualification-execution-plan-v0.1.schema.json"
)
EXECUTOR_STATE_V02_SCHEMA_PATH = SCHEMA_PATH.with_name(
    "mathaudit-qualification-executor-state-v0.2.schema.json"
)
EXECUTOR_STATE_V03_SCHEMA_PATH = SCHEMA_PATH.with_name(
    "mathaudit-qualification-executor-state-v0.3.schema.json"
)
EXECUTOR_STATE_V04_SCHEMA_PATH = SCHEMA_PATH.with_name(
    "mathaudit-qualification-executor-state-v0.4.schema.json"
)
PARTIAL_TRACE_SCHEMA_PATH = SCHEMA_PATH.with_name(
    "mathaudit-mathgoal-partial-trace-v0.1.schema.json"
)


def test_all_shipped_json_schemas_are_valid_draft_2020_12():
    for path in sorted(SCHEMA_PATH.parent.glob("*.schema.json")):
        Draft202012Validator.check_schema(json.loads(path.read_text(encoding="utf-8")))


def test_checked_schema_accepts_canonical_serialization(episode_factory):
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    payload = episode_factory(0, True, False, True).model_dump(mode="json")
    payload["schema_version"] = "0.1"
    errors = sorted(Draft202012Validator(schema).iter_errors(payload), key=lambda item: list(item.path))
    assert errors == []
    assert Episode.model_validate(payload).episode_id == "episode:0"


def test_stable_episode_schema_accepts_default_serialization(episode_factory):
    schema = json.loads(EPISODE_V10_SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    payload = episode_factory(0, True, False, True).model_dump(mode="json")
    assert payload["schema_version"] == "1.0"
    assert list(Draft202012Validator(schema).iter_errors(payload)) == []
    legacy = dict(payload)
    legacy["schema_version"] = "0.1"
    assert list(Draft202012Validator(schema).iter_errors(legacy))


def test_checked_schema_tracks_all_public_episode_fields():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert schema["$id"] == "urn:math-harness-audit:schema:episode:0.1"
    assert set(schema["properties"]) == set(Episode.model_fields)
    assert set(schema["required"]) == {
        "schema_version",
        "episode_id",
        "problem",
        "system",
        "run",
        "adapter",
        "sources",
        "source_observations",
        "evidence",
        "decisions",
        "provenance_edges",
        "labels",
        "final_output",
        "audit_only",
    }


def test_run_manifest_and_deviation_schemas_validate_public_fixtures():
    run_schema = json.loads(RUN_SCHEMA_PATH.read_text(encoding="utf-8"))
    deviation_schema = json.loads(DEVIATION_SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(run_schema)
    Draft202012Validator.check_schema(deviation_schema)
    run_fixture = json.loads(
        (SCHEMA_PATH.parents[1] / "examples" / "fixtures" / "run_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert list(Draft202012Validator(run_schema).iter_errors(run_fixture)) == []
    deviation = {
        "format": "mathaudit-deviation-event-v0.1",
        "event_id": "fixture-event-1",
        "recorded_at": "2026-08-23T00:00:00Z",
        "run_id": "fixture-qualification-001",
        "category": "transport",
        "severity": "minor",
        "affected_problem_ids": ["fixture#1"],
        "description": "Synthetic transport interruption.",
        "action": "Stopped before retry and recorded the event.",
        "outcomes_inspected_before_action": False,
        "requires_rerun": False,
        "author": "fixture",
        "linked_artifact_sha256": None,
    }
    assert list(Draft202012Validator(deviation_schema).iter_errors(deviation)) == []


def test_checked_sample_manifest_schema_accepts_frozen_public_manifests():
    schema = json.loads(SAMPLE_SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    path = SCHEMA_PATH.parents[1] / "examples" / "fixtures" / "sample_manifest.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert list(Draft202012Validator(schema).iter_errors(payload)) == []
    assert verify_sample_manifest_hash(payload)


def test_checked_publication_schema_accepts_fixture_configuration():
    schema = json.loads(PUBLICATION_SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    path = SCHEMA_PATH.parents[1] / "examples" / "fixtures" / "publication_config.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert list(Draft202012Validator(schema).iter_errors(payload)) == []


def test_checked_source_fingerprint_schema_accepts_generated_manifest(tmp_path):
    schema = json.loads(SOURCE_FINGERPRINT_SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    source = tmp_path / "source"
    source.mkdir()
    (source / "module.py").write_text("value = 1\n", encoding="utf-8")
    payload = fingerprint_source_tree(source, system_id="fixture")
    assert list(Draft202012Validator(schema).iter_errors(payload)) == []


def test_compute_authorization_schema_accepts_pending_template():
    schema = json.loads(COMPUTE_AUTHORIZATION_SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    template = json.loads(
        (
            SCHEMA_PATH.parents[1]
            / "examples"
            / "fixtures"
            / "compute_authorization_pending.json"
        ).read_text(encoding="utf-8")
    )
    assert list(Draft202012Validator(schema).iter_errors(template)) == []


def test_execution_plan_schema_accepts_compiled_pending_plan():
    schema = json.loads(EXECUTION_PLAN_SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    systems = ["icma", "mathgoal", "mathrouter"]
    bundle = {
        "format": "mathaudit-input-bundle-v0.1",
        "schedule_seed": 20260823,
        "system_ids": systems,
        "tasks": [
            {
                "idx": idx,
                "problem_id": "fixture-%d" % idx,
                "problem_sha256": "%064x" % (idx + 1),
                "stratum": "fixture",
                "system_order": systems,
            }
            for idx in range(50)
        ],
        "bundle_sha256": "f" * 64,
    }
    authorization = {
        "format": "mathaudit-compute-authorization-v0.1",
        "authorization_id": "fixture-q",
        "status": "pending",
        "scope": "qualification_q",
        "systems": [
            {
                "system_id": system_id,
                "episode_cap": 50,
                "episode_timeout_s": 1200,
                "summed_wall_time_cap_s": 45000,
            }
            for system_id in systems
        ],
    }
    payload = compile_qualification_execution_plan(bundle, authorization)
    assert list(Draft202012Validator(schema).iter_errors(payload)) == []


def test_executor_state_v02_schema_accepts_serial_terminal_state():
    schema = json.loads(EXECUTOR_STATE_V02_SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    payload = {
        "format": "mathaudit-qualification-executor-state-v0.2",
        "authorization_id": "fixture-q",
        "plan_sha256": "a" * 64,
        "status": "completed",
        "started_at": "2026-08-23T00:00:00Z",
        "updated_at": "2026-08-23T00:00:01Z",
        "ended_at": "2026-08-23T00:00:01Z",
        "worker_count": 1,
        "current_episodes": [],
        "episodes": [],
        "contains_prompt_or_response_text": False,
    }
    payload["state_sha256"] = sha256_json(payload)
    assert list(Draft202012Validator(schema).iter_errors(payload)) == []


def test_executor_state_v03_schema_accepts_exception_terminal_state():
    schema = json.loads(EXECUTOR_STATE_V03_SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    payload = {
        "format": "mathaudit-qualification-executor-state-v0.3",
        "authorization_id": "fixture-q",
        "plan_sha256": "a" * 64,
        "status": "stopped_failure",
        "started_at": "2026-08-23T00:00:00Z",
        "updated_at": "2026-08-23T00:30:00Z",
        "ended_at": "2026-08-23T00:30:00Z",
        "worker_count": 1,
        "current_episodes": [],
        "episodes": [
            {
                "sequence": 0,
                "episode_id": "q-0000-mathgoal-0",
                "system_id": "mathgoal",
                "idx": 0,
                "credential_slot": 1,
                "started_at": "2026-08-23T00:00:00Z",
                "status": "runner_or_provider_failure",
                "wall_time_s": 1800.0,
                "attempts": [
                    {
                        "attempt": 0,
                        "return_code": None,
                        "timed_out": True,
                        "wall_time_s": 1800.0,
                        "request_count": 1,
                        "request_statuses": ["transport_failed"],
                        "valid_full_trace": False,
                        "exception_type": "TimeoutError",
                    }
                ],
                "output_relative_path": None,
                "ended_at": "2026-08-23T00:30:00Z",
            }
        ],
        "contains_prompt_or_response_text": False,
    }
    payload["state_sha256"] = sha256_json(payload)
    assert list(Draft202012Validator(schema).iter_errors(payload)) == []


def test_partial_trace_and_executor_v04_schemas_accept_timeout_checkpoint():
    checkpoint = {
        "format": "mathaudit-mathgoal-partial-trace-v0.1",
        "problem_id": "9",
        "status": "in_progress",
        "trace_count": 1,
        "traces": [{"event": "candidate", "content": "private"}],
        "contains_gold": False,
        "contains_prompt_or_response_text": True,
        "private": True,
    }
    checkpoint["checkpoint_sha256"] = sha256_json(checkpoint)
    checkpoint_schema = json.loads(PARTIAL_TRACE_SCHEMA_PATH.read_text(encoding="utf-8"))
    assert list(Draft202012Validator(checkpoint_schema).iter_errors(checkpoint)) == []

    payload = {
        "format": "mathaudit-qualification-executor-state-v0.4",
        "authorization_id": "fixture-q8",
        "plan_sha256": "a" * 64,
        "status": "stopped_failure",
        "started_at": "2026-08-24T00:00:00Z",
        "updated_at": "2026-08-24T00:30:00Z",
        "ended_at": "2026-08-24T00:30:00Z",
        "worker_count": 1,
        "current_episodes": [],
        "episodes": [
            {
                "sequence": 27,
                "episode_id": "q-0027-mathgoal-9",
                "system_id": "mathgoal",
                "idx": 9,
                "credential_slot": 1,
                "started_at": "2026-08-24T00:00:00Z",
                "status": "timeout_partial_trace",
                "wall_time_s": 1800,
                "attempts": [
                    {
                        "attempt": 0,
                        "return_code": None,
                        "timed_out": True,
                        "wall_time_s": 1800,
                        "request_count": 18,
                        "request_statuses": ["completed"],
                        "valid_full_trace": False,
                    }
                ],
                "output_relative_path": None,
                "partial_trace_relative_path": "attempts/q/attempt-0/partial-trace.json",
                "partial_trace_sha256": "b" * 64,
                "partial_trace_records": 18,
                "ended_at": "2026-08-24T00:30:00Z",
            }
        ],
        "contains_prompt_or_response_text": False,
    }
    payload["state_sha256"] = sha256_json(payload)
    state_schema = json.loads(EXECUTOR_STATE_V04_SCHEMA_PATH.read_text(encoding="utf-8"))
    assert list(Draft202012Validator(state_schema).iter_errors(payload)) == []
