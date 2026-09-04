# SPDX-License-Identifier: MIT

import copy

import pytest

from mathaudit.execution import (
    compile_qualification_continuation_plan,
    compile_qualification_execution_plan,
    compile_qualification_replacement_plan,
    verify_qualification_execution_plan,
)
from mathaudit.hashing import sha256_json


def _bundle():
    systems = ["icma", "mathgoal", "mathrouter"]
    tasks = []
    for idx in range(50):
        shift = idx % len(systems)
        order = systems[shift:] + systems[:shift]
        tasks.append(
            {
                "idx": idx,
                "problem_id": "fixture-%d" % idx,
                "problem_sha256": "%064x" % (idx + 1),
                "stratum": "standard" if idx < 25 else "hard",
                "system_order": order,
            }
        )
    return {
        "format": "mathaudit-input-bundle-v0.1",
        "schedule_seed": 20260823,
        "system_ids": systems,
        "tasks": tasks,
        "bundle_sha256": "f" * 64,
    }


def _authorization(status="pending"):
    systems = []
    for system_id, timeout, wall_cap in (
        ("mathrouter", 1200, 54000),
        ("icma", 1200, 45000),
        ("mathgoal", 1800, 54000),
    ):
        systems.append(
            {
                "system_id": system_id,
                "episode_cap": 50,
                "episode_timeout_s": timeout,
                "summed_wall_time_cap_s": wall_cap,
            }
        )
    return {
        "format": "mathaudit-compute-authorization-v0.1",
        "authorization_id": "fixture-q",
        "status": status,
        "scope": "qualification_q",
        "systems": systems,
    }


def test_pending_plan_is_deterministic_but_not_runnable():
    plan = compile_qualification_execution_plan(_bundle(), _authorization())
    assert plan["runnable"] is False
    assert plan["task_count"] == 50
    assert plan["episode_count"] == 150
    assert [entry["system_id"] for entry in plan["entries"][:3]] == [
        "icma",
        "mathgoal",
        "mathrouter",
    ]
    assert plan["plan_sha256"] == sha256_json(
        {key: value for key, value in plan.items() if key != "plan_sha256"}
    )
    assert all(item["wall_cap_can_stop_before_episode_cap"] for item in plan["systems"])


def test_authorized_status_only_changes_runnable_flag_and_hash():
    pending = compile_qualification_execution_plan(_bundle(), _authorization())
    authorized = compile_qualification_execution_plan(
        _bundle(), _authorization(status="authorized")
    )
    assert authorized["runnable"] is True
    assert authorized["entries"] == pending["entries"]
    assert authorized["plan_sha256"] != pending["plan_sha256"]


def test_plan_verifier_rejects_any_schedule_edit():
    bundle = _bundle()
    authorization = _authorization()
    plan = compile_qualification_execution_plan(bundle, authorization)
    summary = verify_qualification_execution_plan(plan, bundle, authorization)
    assert summary["episode_count"] == 150
    plan["entries"][0]["system_id"] = "mathgoal"
    with pytest.raises(ValueError, match="differs"):
        verify_qualification_execution_plan(plan, bundle, authorization)


def test_schedule_omission_duplicate_idx_and_system_drift_are_rejected():
    bundle = _bundle()
    bundle["tasks"][0]["system_order"] = ["icma", "mathgoal"]
    with pytest.raises(ValueError, match="every registered system"):
        compile_qualification_execution_plan(bundle, _authorization())

    bundle = _bundle()
    bundle["tasks"][1]["idx"] = 0
    with pytest.raises(ValueError, match="unique integers"):
        compile_qualification_execution_plan(bundle, _authorization())

    authorization = _authorization()
    authorization["systems"][0] = copy.deepcopy(authorization["systems"][1])
    with pytest.raises(ValueError, match="authorization system set"):
        compile_qualification_execution_plan(_bundle(), authorization)


def _stopped_source_state(source_plan, restart=11):
    episodes = []
    for entry in source_plan["entries"]:
        if entry["sequence"] > restart:
            break
        completed = entry["sequence"] < restart
        episodes.append(
            {
                "sequence": entry["sequence"],
                "episode_id": "q-%04d-%s-%d"
                % (entry["sequence"], entry["system_id"], entry["idx"]),
                "system_id": entry["system_id"],
                "idx": entry["idx"],
                "status": "completed" if completed else "runner_or_provider_failure",
                "attempts": [{"valid_full_trace": completed}],
            }
        )
    state = {
        "format": "mathaudit-qualification-executor-state-v0.3",
        "authorization_id": source_plan["authorization_id"],
        "plan_sha256": source_plan["plan_sha256"],
        "status": "stopped_failure",
        "current_episodes": [],
        "episodes": episodes,
    }
    state["state_sha256"] = sha256_json(state)
    return state


def _continuation_authorization(source_plan, source_state, status="pending", restart=11):
    suffix = [entry for entry in source_plan["entries"] if entry["sequence"] >= restart]
    counts = {
        system_id: sum(entry["system_id"] == system_id for entry in suffix)
        for system_id in ("mathrouter", "icma", "mathgoal")
    }
    return {
        "format": "mathaudit-compute-authorization-v0.2",
        "authorization_id": "fixture-q-continuation",
        "status": status,
        "scope": "qualification_q",
        "total_budget": {"episode_cap": len(suffix)},
        "continuation": {
            "source_authorization_id": source_plan["authorization_id"],
            "source_plan_sha256": source_plan["plan_sha256"],
            "source_state_sha256": source_state["state_sha256"],
            "source_closeout_sha256": "b" * 64,
            "completed_prefix_episode_count": restart,
            "restart_sequence": restart,
            "final_target_episode_count": 150,
        },
        "systems": [
            {
                "system_id": system_id,
                "episode_cap": counts[system_id],
                "episode_timeout_s": 1800 if system_id == "mathgoal" else 1200,
                "summed_wall_time_cap_s": 40000,
            }
            for system_id in ("mathrouter", "icma", "mathgoal")
        ],
    }


def test_continuation_plan_reruns_failed_boundary_and_preserves_suffix():
    bundle = _bundle()
    source_plan = compile_qualification_execution_plan(bundle, _authorization(status="authorized"))
    source_state = _stopped_source_state(source_plan)
    authorization = _continuation_authorization(source_plan, source_state)
    plan = compile_qualification_continuation_plan(
        bundle,
        authorization,
        source_plan=source_plan,
        source_state=source_state,
    )
    assert plan["runnable"] is False
    assert plan["episode_count"] == 139
    assert plan["entries"][0]["sequence"] == 11
    assert plan["entries"][-1]["sequence"] == 149
    assert sum(item["episode_count"] for item in plan["systems"]) == 139
    authorized = copy.deepcopy(authorization)
    authorized["status"] = "authorized"
    runnable = compile_qualification_continuation_plan(
        bundle,
        authorized,
        source_plan=source_plan,
        source_state=source_state,
    )
    summary = verify_qualification_execution_plan(
        runnable,
        bundle,
        authorized,
        source_plan=source_plan,
        source_state=source_state,
    )
    assert summary["runnable"] is True
    assert summary["episode_count"] == 139

    legacy = copy.deepcopy(runnable)
    legacy["notes"] = [
        "Provider-free continuation compilation only; runnable=true is necessary but not sufficient.",
        "Sequences before restart_sequence are inherited only from the outcome-blind source closeout.",
        "The failed boundary sequence is rerun; no failed or incomplete trace is inherited.",
    ]
    legacy.pop("plan_sha256")
    legacy["plan_sha256"] = sha256_json(legacy)
    legacy_summary = verify_qualification_execution_plan(
        legacy,
        bundle,
        authorized,
        source_plan=source_plan,
        source_state=source_state,
    )
    assert legacy_summary["plan_sha256"] == legacy["plan_sha256"]

    rehashed_tamper = copy.deepcopy(legacy)
    rehashed_tamper["entries"][0]["idx"] += 1
    rehashed_tamper.pop("plan_sha256")
    rehashed_tamper["plan_sha256"] = sha256_json(rehashed_tamper)
    with pytest.raises(ValueError, match="deterministic compilation"):
        verify_qualification_execution_plan(
            rehashed_tamper,
            bundle,
            authorized,
            source_plan=source_plan,
            source_state=source_state,
        )


def test_continuation_plan_rejects_tampered_source_state():
    bundle = _bundle()
    source_plan = compile_qualification_execution_plan(bundle, _authorization(status="authorized"))
    source_state = _stopped_source_state(source_plan)
    authorization = _continuation_authorization(source_plan, source_state)
    source_state["episodes"][0]["status"] = "runner_or_provider_failure"
    with pytest.raises(ValueError, match="self-hash"):
        compile_qualification_continuation_plan(
            bundle,
            authorization,
            source_plan=source_plan,
            source_state=source_state,
        )


def test_skip_boundary_continuation_defers_failed_slot_and_compiles_only_unattempted_suffix():
    bundle = _bundle()
    source_plan = compile_qualification_execution_plan(bundle, _authorization(status="authorized"))
    source_state = _stopped_source_state(source_plan, restart=81)
    suffix = [entry for entry in source_plan["entries"] if entry["sequence"] >= 82]
    counts = {
        system_id: sum(entry["system_id"] == system_id for entry in suffix)
        for system_id in ("mathrouter", "icma", "mathgoal")
    }
    authorization = {
        "format": "mathaudit-compute-authorization-v0.3",
        "authorization_id": "fixture-q-skip-boundary",
        "status": "authorized",
        "scope": "qualification_q",
        "total_budget": {"episode_cap": 68},
        "continuation": {
            "source_authorization_id": source_plan["authorization_id"],
            "source_plan_sha256": source_plan["plan_sha256"],
            "source_state_sha256": source_state["state_sha256"],
            "source_closeout_sha256": "b" * 64,
            "completed_prefix_episode_count": 81,
            "restart_sequence": 82,
            "final_target_episode_count": 150,
            "deferred_replacement_count": 1,
            "deferred_replacement_sequence": 81,
        },
        "systems": [
            {
                "system_id": system_id,
                "episode_cap": counts[system_id],
                "episode_timeout_s": 1800 if system_id == "mathgoal" else 1200,
                "summed_wall_time_cap_s": 40000,
            }
            for system_id in ("mathrouter", "icma", "mathgoal")
        ],
    }
    plan = compile_qualification_continuation_plan(
        bundle,
        authorization,
        source_plan=source_plan,
        source_state=source_state,
    )
    assert plan["format"] == "mathaudit-qualification-execution-plan-v0.3"
    assert plan["episode_count"] == 68
    assert [entry["sequence"] for entry in plan["entries"]] == list(range(82, 150))
    summary = verify_qualification_execution_plan(
        plan,
        bundle,
        authorization,
        source_plan=source_plan,
        source_state=source_state,
    )
    assert summary["runnable"] is True
    assert summary["episode_count"] == 68

    tampered = copy.deepcopy(authorization)
    tampered["continuation"]["deferred_replacement_sequence"] = 80
    with pytest.raises(ValueError, match="replacement sequence"):
        compile_qualification_continuation_plan(
            bundle,
            tampered,
            source_plan=source_plan,
            source_state=source_state,
        )


def test_nested_continuation_reruns_second_failed_boundary_without_sequence_drift():
    bundle = _bundle()
    full_plan = compile_qualification_execution_plan(bundle, _authorization(status="authorized"))
    first_state = _stopped_source_state(full_plan, restart=11)
    first_authorization = _continuation_authorization(
        full_plan, first_state, status="authorized", restart=11
    )
    first_plan = compile_qualification_continuation_plan(
        bundle,
        first_authorization,
        source_plan=full_plan,
        source_state=first_state,
    )
    second_state = _stopped_source_state(first_plan, restart=27)
    second_authorization = _continuation_authorization(
        first_plan, second_state, status="authorized", restart=27
    )
    second_plan = compile_qualification_continuation_plan(
        bundle,
        second_authorization,
        source_plan=first_plan,
        source_state=second_state,
    )

    assert second_plan["episode_count"] == 123
    assert [entry["sequence"] for entry in second_plan["entries"]] == list(range(27, 150))
    assert {item["system_id"]: item["episode_count"] for item in second_plan["systems"]} == {
        "mathrouter": 41,
        "icma": 41,
        "mathgoal": 41,
    }
    summary = verify_qualification_execution_plan(
        second_plan,
        bundle,
        second_authorization,
        source_plan=first_plan,
        source_state=second_state,
    )
    assert summary["runnable"] is True
    assert summary["episode_count"] == 123


def _replacement_fixture(bundle, source_plan):
    sequences = [81, 87, 104, 115, 132, 143, 146, 147]
    missing_slots = []
    for sequence in sequences:
        entry = source_plan["entries"][sequence]
        missing_slots.append(
            {
                "run_id": "q11",
                "sequence": sequence,
                "system_id": entry["system_id"],
                "idx": entry["idx"],
                "status": "runner_or_provider_failure",
                "attempt_count": 1,
                "valid_full_trace": False,
            }
        )
    inventory = {
        "format": "mathaudit-q11-postrun-replacement-inventory-v0.1",
        "outcome_blind": True,
        "contains_prompt_or_response_text": False,
        "target_episode_count": 150,
        "complete_full_trace_slot_count": 142,
        "missing_full_trace_slot_count": 8,
        "missing_slots": missing_slots,
        "lineage_states": [{"run_id": "q11", "state_sha256": "a" * 64}],
    }
    inventory["inventory_sha256"] = sha256_json(inventory)
    counts = {
        system_id: sum(
            source_plan["entries"][sequence]["system_id"] == system_id for sequence in sequences
        )
        for system_id in ("mathrouter", "icma", "mathgoal")
    }
    authorization = {
        "format": "mathaudit-compute-authorization-v0.5",
        "authorization_id": "fixture-q-replacements",
        "status": "authorized",
        "scope": "qualification_q",
        "total_budget": {"episode_cap": 8},
        "replacement": {
            "source_schedule_plan_sha256": source_plan["plan_sha256"],
            "source_inventory_sha256": inventory["inventory_sha256"],
            "source_q11_state_sha256": "a" * 64,
            "source_q11_closeout_sha256": "b" * 64,
            "complete_slot_count_before_replacement": 142,
            "replacement_sequences": sequences,
            "final_target_episode_count": 150,
        },
        "systems": [
            {
                "system_id": system_id,
                "episode_cap": counts[system_id],
                "episode_timeout_s": 2700 if system_id == "mathgoal" else 1200,
                "summed_wall_time_cap_s": counts[system_id] * 2700,
            }
            for system_id in ("mathrouter", "icma", "mathgoal")
        ],
    }
    return authorization, inventory, sequences


def test_replacement_plan_compiles_only_the_frozen_missing_sequence_set():
    bundle = _bundle()
    source_plan = compile_qualification_execution_plan(bundle, _authorization(status="authorized"))
    authorization, inventory, sequences = _replacement_fixture(bundle, source_plan)
    plan = compile_qualification_replacement_plan(
        bundle,
        authorization,
        source_plan=source_plan,
        replacement_inventory=inventory,
    )

    assert plan["format"] == "mathaudit-qualification-execution-plan-v0.5"
    assert plan["episode_count"] == 8
    assert [entry["sequence"] for entry in plan["entries"]] == sequences
    assert all(
        entry["episode_timeout_s"]
        == next(
            item["episode_timeout_s"]
            for item in authorization["systems"]
            if item["system_id"] == entry["system_id"]
        )
        for entry in plan["entries"]
    )
    summary = verify_qualification_execution_plan(
        plan,
        bundle,
        authorization,
        source_plan=source_plan,
        replacement_inventory=inventory,
    )
    assert summary == {
        "plan_sha256": plan["plan_sha256"],
        "task_count": 50,
        "episode_count": 8,
        "runnable": True,
    }


def test_replacement_plan_rejects_inventory_or_schedule_drift():
    bundle = _bundle()
    source_plan = compile_qualification_execution_plan(bundle, _authorization(status="authorized"))
    authorization, inventory, _ = _replacement_fixture(bundle, source_plan)
    inventory["missing_slots"][0]["idx"] += 1
    inventory.pop("inventory_sha256")
    inventory["inventory_sha256"] = sha256_json(inventory)
    authorization["replacement"]["source_inventory_sha256"] = inventory["inventory_sha256"]
    with pytest.raises(ValueError, match="does not match the frozen schedule"):
        compile_qualification_replacement_plan(
            bundle,
            authorization,
            source_plan=source_plan,
            replacement_inventory=inventory,
        )
