import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from mathaudit.executor_state import migrate_executor_state_v03
from mathaudit.hashing import sha256_json


def _legacy_failure_state():
    payload = {
        "format": "mathaudit-qualification-executor-state-v0.2",
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
            }
        ],
        "contains_prompt_or_response_text": False,
    }
    payload["state_sha256"] = sha256_json(payload)
    return payload


def test_migrate_executor_state_v03_preserves_source_and_validates():
    root = Path(__file__).resolve().parents[1]
    source = _legacy_failure_state()
    before = copy.deepcopy(source)
    migrated = migrate_executor_state_v03(source)
    assert source == before
    assert migrated["migrated_from"] == {
        "format": before["format"],
        "state_sha256": before["state_sha256"],
    }
    assert migrated["episodes"][0]["output_relative_path"] is None
    assert migrated["episodes"][0]["ended_at"] == before["ended_at"]
    schema = json.loads(
        (root / "schemas/mathaudit-qualification-executor-state-v0.3.schema.json").read_text(
            encoding="utf-8"
        )
    )
    assert list(Draft202012Validator(schema).iter_errors(migrated)) == []


def test_migrate_executor_state_v03_rejects_hash_mismatch():
    source = _legacy_failure_state()
    source["updated_at"] = "tampered"
    with pytest.raises(ValueError, match="self-hash"):
        migrate_executor_state_v03(source)
