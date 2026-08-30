"""Outcome-blind closeout of qualification execution artifacts."""

from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .adapters import RunContext
from .budget import verify_budget_ledger
from .coverage import adapter_coverage
from .execution import verify_qualification_execution_plan
from .executor_state import verify_executor_state_self_hash
from .hashing import sha256_json
from .ingest import ingest_payloads, load_problem_manifest
from .io import write_episodes
from .qualification import verify_qualification_authorization

CLOSEOUT_FORMAT = "mathaudit-qualification-closeout-v0.1"
HEALTH_FORMAT = "mathaudit-qualification-health-v0.2"
HEALTH_FORMATS = {
    "mathaudit-qualification-health-v0.1",
    HEALTH_FORMAT,
}
STATE_FORMATS = {
    "mathaudit-qualification-executor-state-v0.1",
    "mathaudit-qualification-executor-state-v0.2",
    "mathaudit-qualification-executor-state-v0.3",
    "mathaudit-qualification-executor-state-v0.4",
}
SYSTEM_IDS = ("mathrouter", "icma", "mathgoal")


def _load_object(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("JSON document must be an object: %s" % path)
    return payload


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _with_hash(payload: Dict[str, Any], field: str) -> Dict[str, Any]:
    result = copy.deepcopy(payload)
    result.pop(field, None)
    result[field] = sha256_json(result)
    return result


def _verify_executor_state(
    state: Dict[str, Any], authorization: Dict[str, Any], plan: Dict[str, Any]
) -> List[Dict[str, Any]]:
    if state.get("format") not in STATE_FORMATS:
        raise ValueError("unsupported qualification executor state")
    verify_executor_state_self_hash(state)
    if state.get("authorization_id") != authorization["authorization_id"]:
        raise ValueError("executor state authorization mismatch")
    if state.get("plan_sha256") != plan["plan_sha256"]:
        raise ValueError("executor state plan mismatch")
    current = (
        state.get("current_episodes")
        if state.get("format")
        in {
            "mathaudit-qualification-executor-state-v0.2",
            "mathaudit-qualification-executor-state-v0.3",
            "mathaudit-qualification-executor-state-v0.4",
        }
        else ([state.get("current_episode")] if state.get("current_episode") is not None else [])
    )
    if current:
        raise ValueError("executor state contains an unfinished episode")
    if state.get("contains_prompt_or_response_text") is not False:
        raise ValueError("executor state text policy violation")
    if state.get("status") not in {"completed", "stopped_failure", "stopped_wall_cap"}:
        raise ValueError("executor state is not terminal")
    episodes = state.get("episodes")
    if not isinstance(episodes, list):
        raise ValueError("executor state episodes must be a list")
    if len(episodes) > len(plan["entries"]):
        raise ValueError("executor state exceeds the registered plan")
    expected_prefix = plan["entries"][: len(episodes)]
    for position, (observed, expected) in enumerate(
        zip(episodes, expected_prefix, strict=True)
    ):
        if not isinstance(observed, dict):
            raise ValueError("executor episode is not an object")
        for field in ("sequence", "system_id", "idx", "output_relative_path"):
            expected_value = (
                expected[field]
                if field != "output_relative_path" or observed.get("status") == "completed"
                else None
            )
            if observed.get(field) != expected_value:
                raise ValueError("executor episode %d differs from plan: %s" % (position, field))
        attempts = observed.get("attempts")
        if not isinstance(attempts, list) or not 1 <= len(attempts) <= 2:
            raise ValueError("executor episode has invalid attempt count")
        if len(attempts) == 2:
            first_statuses = attempts[0].get("request_statuses")
            if not first_statuses or any(value != "transport_failed" for value in first_statuses):
                raise ValueError("executor retried an ineligible first attempt")
        if observed.get("status") == "completed" and not attempts[-1].get("valid_full_trace"):
            raise ValueError("completed executor episode lacks a valid full trace")
    if state.get("status") == "completed" and len(episodes) != len(plan["entries"]):
        raise ValueError("completed executor state does not cover the full plan")
    return episodes


def _verify_ledger_episode_join(
    ledger: Dict[str, Any], state_episodes: List[Dict[str, Any]]
) -> None:
    if any(item.get("status") == "reserved" for item in ledger["requests"]):
        raise ValueError("budget ledger contains unfinished request reservations")
    ledger_episodes = ledger["episodes"]
    if len(ledger_episodes) != len(state_episodes):
        raise ValueError("budget ledger and executor episode counts differ")
    by_id = {item.get("episode_id"): item for item in ledger_episodes}
    if len(by_id) != len(ledger_episodes):
        raise ValueError("budget ledger episode IDs are duplicated")
    for state_row in state_episodes:
        ledger_row = by_id.get(state_row.get("episode_id"))
        if ledger_row is None:
            raise ValueError("executor episode is absent from budget ledger")
        if ledger_row.get("system_id") != state_row.get("system_id"):
            raise ValueError("ledger/state system mismatch")
        state_status = state_row.get("status")
        ledger_status = ledger_row.get("status")
        # The executor preserves a partial trace as a terminal timeout status,
        # while the budget gateway records the same non-retryable terminal
        # reservation as a runner/provider failure.  Treat this one pair as an
        # explicit metadata equivalence; all other status mismatches remain
        # fail-closed.
        status_matches = ledger_status == state_status or (
            state_status == "timeout_partial_trace"
            and ledger_status == "runner_or_provider_failure"
        )
        if not status_matches:
            raise ValueError("ledger/state status mismatch")
        if abs(float(ledger_row["wall_time_s"]) - float(state_row["wall_time_s"])) > 1e-9:
            raise ValueError("ledger/state wall-time mismatch")


def _raw_payloads(
    raw_dir: Path,
    plan: Dict[str, Any],
    state_episodes: List[Dict[str, Any]],
    system_id: str,
) -> Tuple[List[Tuple[Dict[str, Any], str]], List[Dict[str, Any]]]:
    completed_sequences = {
        int(item["sequence"])
        for item in state_episodes
        if item.get("status") == "completed" and item.get("system_id") == system_id
    }
    expected_entries = [
        item
        for item in plan["entries"]
        if item["system_id"] == system_id and int(item["sequence"]) in completed_sequences
    ]
    expected_paths = {str(item["output_relative_path"]) for item in expected_entries}
    system_root = raw_dir / system_id
    observed_paths = (
        {
            path.relative_to(raw_dir).as_posix()
            for path in system_root.glob("*.json")
            if path.is_file()
        }
        if system_root.is_dir()
        else set()
    )
    if observed_paths != expected_paths:
        raise ValueError("raw output set differs from completed plan for %s" % system_id)
    payloads: List[Tuple[Dict[str, Any], str]] = []
    index: List[Dict[str, Any]] = []
    for entry in expected_entries:
        relative = str(entry["output_relative_path"])
        path = raw_dir / relative
        payload = _load_object(path)
        payloads.append((payload, relative))
        index.append(
            {
                "sequence": entry["sequence"],
                "idx": entry["idx"],
                "problem_id": entry["problem_id"],
                "relative_path": relative,
                "sha256": _file_sha256(path),
                "bytes": path.stat().st_size,
            }
        )
    return payloads, index


def _partial_trace_index(
    raw_dir: Path,
    state_rows: List[Dict[str, Any]],
    system_id: str,
) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    raw_root = raw_dir.resolve()
    for row in state_rows:
        if row.get("system_id") != system_id:
            continue
        fields = (
            row.get("partial_trace_relative_path"),
            row.get("partial_trace_sha256"),
            row.get("partial_trace_records"),
        )
        if all(value is None for value in fields):
            continue
        if any(value is None for value in fields):
            raise ValueError("executor partial-trace provenance is incomplete")
        path = (raw_dir / str(fields[0])).resolve()
        try:
            path.relative_to(raw_root)
        except ValueError as exc:
            raise ValueError("partial trace escapes the raw output directory") from exc
        if not path.is_file() or _file_sha256(path) != fields[1]:
            raise ValueError("partial trace artifact hash mismatch")
        payload = _load_object(path)
        claimed = payload.get("checkpoint_sha256")
        candidate = copy.deepcopy(payload)
        candidate.pop("checkpoint_sha256", None)
        traces = payload.get("traces")
        if (
            payload.get("format") != "mathaudit-mathgoal-partial-trace-v0.1"
            or payload.get("problem_id") != str(row["idx"])
            or payload.get("contains_gold") is not False
            or payload.get("private") is not True
            or not isinstance(traces, list)
            or len(traces) != fields[2]
            or payload.get("trace_count") != fields[2]
            or claimed != sha256_json(candidate)
        ):
            raise ValueError("partial trace artifact validation failed")
        records.append(
            {
                "sequence": row["sequence"],
                "idx": row["idx"],
                "relative_path": str(fields[0]),
                "sha256": str(fields[1]),
                "trace_records": int(fields[2]),
                "checkpoint_sha256": str(claimed),
            }
        )
    return records


def _finalize_run_manifest(
    planned: Dict[str, Any],
    state: Dict[str, Any],
    state_rows: List[Dict[str, Any]],
    artifacts: List[Dict[str, Any]],
) -> Dict[str, Any]:
    result = copy.deepcopy(planned)
    completed = sum(item["status"] == "completed" for item in state_rows)
    timed_out = sum("timeout" in str(item["status"]) for item in state_rows)
    quota_transport = sum(
        item["status"] in {"quota_failure", "transport_failure"} for item in state_rows
    )
    result["status"] = (
        "completed"
        if state.get("status") == "completed" and completed == result["budget"]["episode_cap"]
        else "stopped"
    )
    result["started_at"] = state.get("started_at")
    result["ended_at"] = state.get("ended_at") or state.get("updated_at")
    result["counts"] = {
        "attempted": len(state_rows),
        "completed": completed,
        "failed": len(state_rows) - completed - timed_out,
        "timed_out": timed_out,
        "quota_or_transport_failed": quota_transport,
        "excluded": 0,
    }
    result["artifacts"] = artifacts
    result["notes"] = list(result.get("notes") or []) + [
        "Closed outcome-blind from executor state and budget ledger; no correctness aggregate computed."
    ]
    return result


def closeout_qualification(
    *,
    authorization_path: Path,
    ledger_path: Path,
    plan_path: Path,
    bundle_manifest_path: Path,
    executor_state_path: Path,
    raw_dir: Path,
    problems_path: Path,
    planned_manifest_dir: Path,
    output_dir: Path,
    source_plan_path: Optional[Path] = None,
    source_state_path: Optional[Path] = None,
    replacement_inventory_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Validate and close a completed/stopped Q run without outcome aggregation."""

    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError("closeout output directory must be absent or empty")
    authorization = _load_object(authorization_path)
    verify_qualification_authorization(authorization)
    plan = _load_object(plan_path)
    bundle = _load_object(bundle_manifest_path)
    source_plan = _load_object(source_plan_path) if source_plan_path is not None else None
    source_state = _load_object(source_state_path) if source_state_path is not None else None
    replacement_inventory = (
        _load_object(replacement_inventory_path)
        if replacement_inventory_path is not None
        else None
    )
    verify_qualification_execution_plan(
        plan,
        bundle,
        authorization,
        source_plan=source_plan,
        source_state=source_state,
        replacement_inventory=replacement_inventory,
    )
    ledger = _load_object(ledger_path)
    ledger_summary = verify_budget_ledger(ledger, authorization)
    state = _load_object(executor_state_path)
    state_episodes = _verify_executor_state(state, authorization, plan)
    _verify_ledger_episode_join(ledger, state_episodes)
    problems = load_problem_manifest(
        problems_path,
        dataset_id="qualification-matched",
        split="test",
        stratum="registered",
    )

    prepared: Dict[str, Dict[str, Any]] = {}
    for system_id in SYSTEM_IDS:
        planned = _load_object(planned_manifest_dir / (system_id + ".json"))
        if (
            planned.get("format") != "mathaudit-run-manifest-v0.1"
            or planned.get("status") != "planned"
            or planned.get("system", {}).get("system_id") != system_id
        ):
            raise ValueError("planned run manifest is invalid: %s" % system_id)
        payloads, raw_index = _raw_payloads(
            raw_dir, plan, state_episodes, system_id
        )
        run = RunContext(
            run_id=planned["run_id"],
            system_id=system_id,
            system_name=planned["system"]["name"],
            system_version=planned["system"]["version"],
            config=planned["runtime"],
            environment=planned["environment"],
            harness_family="Hermes" if system_id == "mathrouter" else system_id,
            commit=(
                planned["system"]["version"] if system_id == "mathrouter" else None
            ),
            seed=plan["schedule_seed"],
        )
        episodes = ingest_payloads(
            payloads,
            adapter_name=planned["system"]["adapter_name"],
            problems=problems,
            run=run,
        )
        prepared[system_id] = {
            "planned": planned,
            "raw_index": raw_index,
            "episodes": episodes,
            "coverage": adapter_coverage(episodes),
        }

    output_dir.mkdir(parents=True, exist_ok=True)
    registered_by_system = {
        item["system_id"]: int(item["episode_count"])
        for item in plan["systems"]
    }
    health_systems: Dict[str, Any] = {}
    final_manifest_paths: List[Path] = []
    artifact_rows: List[Dict[str, Any]] = []
    for system_id in SYSTEM_IDS:
        item = prepared[system_id]
        system_dir = output_dir / system_id
        system_dir.mkdir(parents=True, exist_ok=True)
        raw_index_payload = {
            "format": "mathaudit-qualification-raw-index-v0.1",
            "system_id": system_id,
            "records": item["raw_index"],
        }
        raw_index_payload["index_sha256"] = sha256_json(raw_index_payload)
        raw_index_path = system_dir / "raw-index.json"
        raw_index_path.write_text(
            json.dumps(raw_index_payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        canonical_path = system_dir / "canonical.jsonl"
        write_episodes(canonical_path, item["episodes"])
        coverage_path = system_dir / "coverage.json"
        coverage_path.write_text(
            json.dumps(item["coverage"], ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        system_state = [
            row for row in state_episodes if row["system_id"] == system_id
        ]
        partial_rows = _partial_trace_index(raw_dir, system_state, system_id)
        artifacts = [
            {
                "role": "raw_index",
                "relative_path": "%s/raw-index.json" % system_id,
                "sha256": _file_sha256(raw_index_path),
                "records": len(item["raw_index"]),
                "private": True,
            },
            {
                "role": "canonical_episodes",
                "relative_path": "%s/canonical.jsonl" % system_id,
                "sha256": _file_sha256(canonical_path),
                "records": len(item["episodes"]),
                "private": True,
            },
            {
                "role": "outcome_blind_coverage",
                "relative_path": "%s/coverage.json" % system_id,
                "sha256": _file_sha256(coverage_path),
                "records": len(item["episodes"]),
                "private": False,
            },
            {
                "role": "budget_ledger",
                "relative_path": "inputs/budget-ledger.json",
                "sha256": _file_sha256(ledger_path),
                "records": ledger["systems"][system_id]["request_count"],
                "private": True,
            },
            {
                "role": "executor_state",
                "relative_path": "inputs/executor-state.json",
                "sha256": _file_sha256(executor_state_path),
                "records": len(system_state),
                "private": True,
            },
        ]
        if partial_rows:
            partial_index_payload = {
                "format": "mathaudit-qualification-partial-trace-index-v0.1",
                "system_id": system_id,
                "records": partial_rows,
                "contains_prompt_or_response_text": False,
            }
            partial_index_payload["index_sha256"] = sha256_json(
                partial_index_payload
            )
            partial_index_path = system_dir / "partial-trace-index.json"
            partial_index_path.write_text(
                json.dumps(partial_index_payload, ensure_ascii=False, indent=2)
                + "\n",
                encoding="utf-8",
            )
            artifacts.insert(
                3,
                {
                    "role": "partial_trace_index",
                    "relative_path": "%s/partial-trace-index.json" % system_id,
                    "sha256": _file_sha256(partial_index_path),
                    "records": len(partial_rows),
                    "private": True,
                },
            )
        final_manifest = _finalize_run_manifest(
            item["planned"], state, system_state, artifacts
        )
        final_manifest_path = system_dir / "run-manifest.final.json"
        final_manifest_path.write_text(
            json.dumps(final_manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        final_manifest_paths.append(final_manifest_path)
        request_rows = [row for row in ledger["requests"] if row["system_id"] == system_id]
        request_statuses = Counter(str(row["status"]) for row in request_rows)
        episode_statuses = Counter(str(row["status"]) for row in system_state)
        health_systems[system_id] = {
            "registered_episodes": registered_by_system[system_id],
            "attempted_episodes": len(system_state),
            "complete_full_trace_episodes": len(item["episodes"]),
            "episode_statuses": dict(sorted(episode_statuses.items())),
            "adapter_fidelity": item["coverage"]["fidelity"],
            "semantic_issue_count": sum(item["coverage"]["semantic_issues"].values()),
            "request_count": len(request_rows),
            "request_statuses": dict(sorted(request_statuses.items())),
            "observed_usage_request_count": ledger["systems"][system_id][
                "observed_usage_request_count"
            ],
            "observed_input_tokens": ledger["systems"][system_id][
                "observed_input_tokens"
            ],
            "observed_output_tokens": ledger["systems"][system_id][
                "observed_output_tokens"
            ],
            "observed_total_tokens": ledger["systems"][system_id][
                "observed_total_tokens"
            ],
            "observed_usage_fraction": (
                ledger["systems"][system_id]["observed_usage_request_count"]
                / len(request_rows)
                if request_rows
                else None
            ),
            "reserved_token_upper": ledger["systems"][system_id]["reserved_token_upper"],
            "reserved_monetary_cny": ledger["systems"][system_id]["reserved_monetary_cny"],
            "summed_episode_wall_time_s": ledger["systems"][system_id][
                "summed_episode_wall_time_s"
            ],
        }
        artifact_rows.extend(
            row
            for row in artifacts
            if row["role"]
            in {
                "raw_index",
                "canonical_episodes",
                "outcome_blind_coverage",
                "partial_trace_index",
            }
        )

    health = {
        "format": HEALTH_FORMAT,
        "authorization_id": authorization["authorization_id"],
        "plan_sha256": plan["plan_sha256"],
        "state_sha256": state["state_sha256"],
        "ledger_sha256": ledger["ledger_sha256"],
        "executor_terminal_status": state["status"],
        "outcome_blind": True,
        "correctness_aggregates_computed": False,
        "forbidden_qualification_statistics": [
            "system_accuracy",
            "phi",
            "cofailure",
            "repair_harm",
            "utilization",
            "system_ranking",
        ],
        "totals": {
            "registered_episodes": plan["episode_count"],
            "attempted_episodes": len(state_episodes),
            "complete_full_trace_episodes": sum(
                len(prepared[system_id]["episodes"]) for system_id in SYSTEM_IDS
            ),
            "request_count": ledger_summary["request_count"],
            "observed_usage_request_count": ledger["totals"][
                "observed_usage_request_count"
            ],
            "observed_input_tokens": ledger["totals"]["observed_input_tokens"],
            "observed_output_tokens": ledger["totals"]["observed_output_tokens"],
            "observed_total_tokens": ledger["totals"]["observed_total_tokens"],
            "observed_usage_fraction": (
                ledger["totals"]["observed_usage_request_count"]
                / ledger_summary["request_count"]
                if ledger_summary["request_count"]
                else None
            ),
            "reserved_token_upper": ledger_summary["reserved_token_upper"],
            "reserved_monetary_cny": ledger_summary["reserved_monetary_cny"],
            "summed_episode_wall_time_s": ledger_summary[
                "summed_episode_wall_time_s"
            ],
        },
        "systems": health_systems,
        "artifacts": artifact_rows,
    }
    health = _with_hash(health, "health_sha256")
    health_path = output_dir / "qualification-health.json"
    health_path.write_text(
        json.dumps(health, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    closeout = {
        "format": CLOSEOUT_FORMAT,
        "authorization_id": authorization["authorization_id"],
        "plan_sha256": plan["plan_sha256"],
        "outcome_blind": True,
        "health_report": {
            "relative_path": "qualification-health.json",
            "sha256": _file_sha256(health_path),
        },
        "final_run_manifests": [
            {
                "system_id": path.parent.name,
                "relative_path": path.relative_to(output_dir).as_posix(),
                "sha256": _file_sha256(path),
            }
            for path in final_manifest_paths
        ],
        "contains_prompt_or_response_text": False,
    }
    closeout = _with_hash(closeout, "closeout_sha256")
    closeout_path = output_dir / "closeout-manifest.json"
    closeout_path.write_text(
        json.dumps(closeout, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return closeout
