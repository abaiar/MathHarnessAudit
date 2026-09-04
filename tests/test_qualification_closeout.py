# SPDX-License-Identifier: MIT

import copy
import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator

from mathaudit.budget import initialize_budget_ledger, record_episode_wall_time
from mathaudit.execution import compile_qualification_execution_plan
from mathaudit.hashing import sha256_json
from mathaudit.qualification_closeout import (
    _partial_trace_index,
    _verify_ledger_episode_join,
    closeout_qualification,
)


def test_ledger_join_accepts_partial_trace_terminal_status_alias():
    state_episodes = [
        {
            "episode_id": "q-0081-mathgoal-27",
            "system_id": "mathgoal",
            "status": "timeout_partial_trace",
            "wall_time_s": 2700.936297,
        }
    ]
    ledger = {
        "requests": [],
        "episodes": [
            {
                "episode_id": "q-0081-mathgoal-27",
                "system_id": "mathgoal",
                "status": "runner_or_provider_failure",
                "wall_time_s": 2700.936297,
            }
        ],
    }
    _verify_ledger_episode_join(ledger, state_episodes)


def _authorization():
    retry = {
        "max_retries": 1,
        "eligible_failure_class": "pre_response_transport_failure_only",
        "forbid_after_any_response": True,
        "forbid_on_parse_failure": True,
        "forbid_on_tool_failure": True,
    }
    systems = []
    for system_id, timeout, wall, tokens, money in (
        ("mathrouter", 1200, 54000, 18000000, 3),
        ("icma", 1200, 45000, 18000000, 3),
        ("mathgoal", 1800, 54000, 24000000, 4),
    ):
        systems.append(
            {
                "system_id": system_id,
                "provider": "fixture",
                "model": "fixture-model",
                "model_revision": "fixture-model",
                "endpoint_class": "fixture",
                "endpoint_url": "https://example.invalid/v1/chat/completions",
                "endpoint_available": True,
                "parameters": {},
                "concurrency": 1,
                "episode_timeout_s": timeout,
                "max_output_tokens": 8192,
                "retry_policy": "fixture transport only",
                "retry_control": retry,
                "episode_cap": 50,
                "token_cap": tokens,
                "currency": "CNY",
                "monetary_cap": money,
                "summed_wall_time_cap_s": wall,
            }
        )
    return {
        "format": "mathaudit-compute-authorization-v0.1",
        "authorization_id": "fixture-q",
        "status": "authorized",
        "scope": "qualification_q",
        "authorized_by": "fixture-owner",
        "authorized_at": "2026-08-23T00:00:00Z",
        "total_budget": {
            "episode_cap": 150,
            "token_cap": 60000000,
            "currency": "CNY",
            "monetary_cap": 10,
            "summed_wall_time_cap_s": 153000,
        },
        "monetary_accounting": {
            "mode": "free_quota",
            "free_quota_confirmed": True,
            "input_cny_per_million_tokens": None,
            "output_cny_per_million_tokens": None,
            "evidence_source": "fixture",
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


def _planned_manifest(authorization, system_id):
    auth = next(item for item in authorization["systems"] if item["system_id"] == system_id)
    fidelity = "A" if system_id == "mathgoal" else "B"
    return {
        "format": "mathaudit-run-manifest-v0.1",
        "run_id": "fixture-%s" % system_id,
        "study_phase": "qualification",
        "status": "planned",
        "system": {
            "system_id": system_id,
            "name": system_id,
            "version": "fixture",
            "source_fingerprint": "a" * 64,
            "adapter_name": system_id,
            "adapter_version": "0.1",
            "adapter_fidelity": fidelity,
        },
        "sample_manifest": {
            "relative_path": "sample.json",
            "sha256": "b" * 64,
            "selected_count": 50,
            "strata": ["standard", "hard"],
        },
        "runtime": {
            key: auth[key]
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
            )
        },
        "budget": {
            "episode_cap": auth["episode_cap"],
            "token_cap": auth["token_cap"],
            "currency": auth["currency"],
            "monetary_cap": auth["monetary_cap"],
            "summed_wall_time_cap_s": auth["summed_wall_time_cap_s"],
            "monetary_accounting": authorization["monetary_accounting"],
        },
        "environment": {
            "os": "fixture-os",
            "python": "3.11.0",
            "dependency_lock_sha256": "c" * 64,
            "container_image": None,
        },
        "started_at": None,
        "ended_at": None,
        "counts": {
            "attempted": 0,
            "completed": 0,
            "failed": 0,
            "timed_out": 0,
            "quota_or_transport_failed": 0,
            "excluded": 0,
        },
        "outcome_blind": True,
        "secrets_recorded": False,
        "deviation_log": None,
        "artifacts": [],
        "notes": [],
    }


def test_partial_trace_index_is_outcome_blind_and_hash_checked(tmp_path):
    relative = "attempts/q-0027-mathgoal-9/attempt-0/partial-trace.json"
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    checkpoint = {
        "format": "mathaudit-mathgoal-partial-trace-v0.1",
        "problem_id": "9",
        "status": "in_progress",
        "trace_count": 1,
        "traces": [{"content": "private model response"}],
        "contains_gold": False,
        "contains_prompt_or_response_text": True,
        "private": True,
    }
    checkpoint["checkpoint_sha256"] = sha256_json(checkpoint)
    path.write_text(json.dumps(checkpoint), encoding="utf-8")
    file_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    state_rows = [
        {
            "sequence": 27,
            "system_id": "mathgoal",
            "idx": 9,
            "partial_trace_relative_path": relative,
            "partial_trace_sha256": file_hash,
            "partial_trace_records": 1,
        }
    ]
    records = _partial_trace_index(tmp_path, state_rows, "mathgoal")
    assert records[0]["trace_records"] == 1
    assert "traces" not in records[0]

    checkpoint["traces"][0]["content"] = "tampered"
    path.write_text(json.dumps(checkpoint), encoding="utf-8")
    try:
        _partial_trace_index(tmp_path, state_rows, "mathgoal")
    except ValueError as exc:
        assert "hash mismatch" in str(exc)
    else:
        raise AssertionError("tampered checkpoint was accepted")


def test_full_qualification_closeout_is_outcome_blind_and_schema_valid(tmp_path):
    root = Path(__file__).resolve().parents[1]
    authorization = _authorization()
    tasks = []
    for idx in range(50):
        tasks.append(
            {
                "idx": idx,
                "problem_id": "fixture#%d" % idx,
                "problem_sha256": "%064x" % (idx + 1),
                "stratum": "standard" if idx < 25 else "hard",
                "system_order": ["mathrouter", "icma", "mathgoal"],
            }
        )
    bundle = {
        "format": "mathaudit-input-bundle-v0.1",
        "system_ids": ["mathrouter", "icma", "mathgoal"],
        "schedule_seed": 20260823,
        "bundle_sha256": "d" * 64,
        "tasks": tasks,
    }
    plan = compile_qualification_execution_plan(bundle, authorization)

    authorization_path = tmp_path / "authorization.json"
    bundle_path = tmp_path / "bundle.json"
    plan_path = tmp_path / "plan.json"
    authorization_path.write_text(json.dumps(authorization), encoding="utf-8")
    bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    problems_path = tmp_path / "problems.jsonl"
    with problems_path.open("w", encoding="utf-8") as handle:
        for idx in range(50):
            handle.write(
                json.dumps(
                    {
                        "idx": idx,
                        "problem": "What is %d + 0?" % idx,
                        "answer": str(idx),
                        "public_problem_id": "fixture#%d" % idx,
                        "source_dataset_id": "fixture",
                        "source_stratum": "standard" if idx < 25 else "hard",
                    }
                )
                + "\n"
            )

    templates = {
        "mathrouter": json.loads(
            (root / "examples/fixtures/mathrouter/1.json").read_text(encoding="utf-8")
        ),
        "icma": json.loads((root / "examples/fixtures/icma/0.json").read_text(encoding="utf-8")),
        "mathgoal": json.loads(
            (root / "examples/fixtures/mathgoal_full.json").read_text(encoding="utf-8")
        ),
    }
    raw_dir = tmp_path / "raw"
    for system_id in ("mathrouter", "icma", "mathgoal"):
        (raw_dir / system_id).mkdir(parents=True)
        for idx in range(50):
            payload = copy.deepcopy(templates[system_id])
            if system_id == "mathgoal":
                payload["problem_id"] = str(idx)
            else:
                payload["idx"] = idx
            (raw_dir / system_id / (str(idx) + ".json")).write_text(
                json.dumps(payload), encoding="utf-8"
            )

    ledger = initialize_budget_ledger(authorization)
    state_rows = []
    for entry in plan["entries"]:
        episode_id = "q-%04d-%s-%d" % (
            entry["sequence"],
            entry["system_id"],
            entry["idx"],
        )
        ledger = record_episode_wall_time(
            ledger,
            authorization,
            system_id=entry["system_id"],
            episode_id=episode_id,
            wall_time_s=0.01,
            status="completed",
        )
        state_rows.append(
            {
                "sequence": entry["sequence"],
                "episode_id": episode_id,
                "system_id": entry["system_id"],
                "idx": entry["idx"],
                "status": "completed",
                "wall_time_s": 0.01,
                "attempts": [
                    {
                        "attempt": 0,
                        "return_code": 0,
                        "timed_out": False,
                        "wall_time_s": 0.01,
                        "request_count": 0,
                        "request_statuses": [],
                        "valid_full_trace": True,
                    }
                ],
                "output_relative_path": entry["output_relative_path"],
                "ended_at": "2026-08-23T00:00:01Z",
            }
        )
    ledger_path = tmp_path / "ledger.json"
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
    state = {
        "format": "mathaudit-qualification-executor-state-v0.1",
        "authorization_id": authorization["authorization_id"],
        "plan_sha256": plan["plan_sha256"],
        "status": "completed",
        "started_at": "2026-08-23T00:00:00Z",
        "updated_at": "2026-08-23T00:00:02Z",
        "ended_at": "2026-08-23T00:00:02Z",
        "current_episode": None,
        "episodes": state_rows,
        "contains_prompt_or_response_text": False,
    }
    state["state_sha256"] = sha256_json(state)
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")

    planned_dir = tmp_path / "planned"
    planned_dir.mkdir()
    for system_id in ("mathrouter", "icma", "mathgoal"):
        (planned_dir / (system_id + ".json")).write_text(
            json.dumps(_planned_manifest(authorization, system_id)), encoding="utf-8"
        )

    output_dir = tmp_path / "closeout"
    closeout = closeout_qualification(
        authorization_path=authorization_path,
        ledger_path=ledger_path,
        plan_path=plan_path,
        bundle_manifest_path=bundle_path,
        executor_state_path=state_path,
        raw_dir=raw_dir,
        problems_path=problems_path,
        planned_manifest_dir=planned_dir,
        output_dir=output_dir,
    )
    assert closeout["outcome_blind"] is True
    health = json.loads((output_dir / "qualification-health.json").read_text(encoding="utf-8"))
    assert health["correctness_aggregates_computed"] is False
    assert health["totals"]["complete_full_trace_episodes"] == 150
    assert health["totals"]["request_count"] == 0
    for system_id in ("mathrouter", "icma", "mathgoal"):
        canonical = (output_dir / system_id / "canonical.jsonl").read_text(encoding="utf-8")
        assert len(canonical.splitlines()) == 50

    for schema_name, payload in (
        ("mathaudit-qualification-health-v0.2.schema.json", health),
        ("mathaudit-qualification-closeout-v0.1.schema.json", closeout),
    ):
        schema = json.loads((root / "schemas" / schema_name).read_text(encoding="utf-8"))
        assert list(Draft202012Validator(schema).iter_errors(payload)) == []
    run_schema = json.loads(
        (root / "schemas/mathaudit-run-manifest-v0.1.schema.json").read_text(encoding="utf-8")
    )
    for system_id in ("mathrouter", "icma", "mathgoal"):
        final_manifest = json.loads(
            (output_dir / system_id / "run-manifest.final.json").read_text(encoding="utf-8")
        )
        assert final_manifest["status"] == "completed"
        assert final_manifest["counts"]["completed"] == 50
        assert list(Draft202012Validator(run_schema).iter_errors(final_manifest)) == []


def test_health_v02_accepts_continuation_system_counts_and_rejects_overflow():
    root = Path(__file__).resolve().parents[1]
    schema = json.loads(
        (root / "schemas/mathaudit-qualification-health-v0.2.schema.json").read_text(
            encoding="utf-8"
        )
    )
    system = {
        "registered_episodes": 41,
        "attempted_episodes": 1,
        "complete_full_trace_episodes": 0,
        "episode_statuses": {"runner_or_provider_failure": 1},
        "adapter_fidelity": {},
        "semantic_issue_count": 0,
        "request_count": 21,
        "request_statuses": {"completed": 18, "transport_failed": 3},
        "observed_usage_request_count": 18,
        "observed_input_tokens": 1,
        "observed_output_tokens": 1,
        "observed_total_tokens": 2,
        "observed_usage_fraction": 18 / 21,
        "reserved_token_upper": 1,
        "reserved_monetary_cny": "0.000000000",
        "summed_episode_wall_time_s": 1800.0,
    }
    health = {
        "format": "mathaudit-qualification-health-v0.2",
        "authorization_id": "fixture-continuation",
        "plan_sha256": "a" * 64,
        "state_sha256": "b" * 64,
        "ledger_sha256": "c" * 64,
        "executor_terminal_status": "stopped_failure",
        "outcome_blind": True,
        "correctness_aggregates_computed": False,
        "forbidden_qualification_statistics": ["system_accuracy"],
        "totals": {
            "registered_episodes": 123,
            "attempted_episodes": 1,
            "complete_full_trace_episodes": 0,
            "request_count": 21,
            "observed_usage_request_count": 18,
            "observed_input_tokens": 1,
            "observed_output_tokens": 1,
            "observed_total_tokens": 2,
            "observed_usage_fraction": 18 / 21,
            "reserved_token_upper": 1,
            "reserved_monetary_cny": "0.000000000",
            "summed_episode_wall_time_s": 1800.0,
        },
        "systems": {
            "mathrouter": copy.deepcopy(system),
            "icma": copy.deepcopy(system),
            "mathgoal": copy.deepcopy(system),
        },
        "artifacts": [],
        "health_sha256": "d" * 64,
    }
    validator = Draft202012Validator(schema)
    assert list(validator.iter_errors(health)) == []
    health["systems"]["mathgoal"]["registered_episodes"] = 51
    assert list(validator.iter_errors(health))
