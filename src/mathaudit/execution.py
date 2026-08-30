# SPDX-License-Identifier: MIT

"""Deterministic, provider-free compilation of qualification execution order."""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

from .executor_state import verify_executor_state_self_hash
from .hashing import sha256_json
from .qualification import (
    CONTINUATION_AUTHORIZATION_FORMATS,
    CONTINUE_AFTER_FAILURE_AUTHORIZATION_FORMAT,
    DEFAULT_SYSTEM_IDS,
    REPLACEMENT_AUTHORIZATION_FORMAT,
    SKIP_BOUNDARY_CONTINUATION_AUTHORIZATION_FORMAT,
)

LEGACY_CONTINUATION_NOTES = [
    "Provider-free continuation compilation only; runnable=true is necessary but not sufficient.",
    "Sequences before restart_sequence are inherited only from the outcome-blind source closeout.",
    "The failed boundary sequence is rerun; no failed or incomplete trace is inherited.",
]

REPLACEMENT_INVENTORY_FORMATS = {
    "mathaudit-q11-postrun-replacement-inventory-v0.1",
    "mathaudit-q12-postrun-replacement-inventory-v0.1",
    "mathaudit-q13-postrun-replacement-inventory-v0.1",
}


def compile_qualification_execution_plan(
    bundle_manifest: Dict[str, Any],
    authorization: Dict[str, Any],
) -> Dict[str, Any]:
    """Compile the frozen task-major blocked schedule without contacting a provider.

    A pending authorization is deliberately accepted for planning, but the
    returned ``runnable`` flag remains false. Provider-facing code must require
    both an authorized record and a green preflight independently.
    """

    if bundle_manifest.get("format") != "mathaudit-input-bundle-v0.1":
        raise ValueError("unsupported input-bundle manifest format")
    if authorization.get("format") != "mathaudit-compute-authorization-v0.1":
        raise ValueError("unsupported compute-authorization format")
    if authorization.get("scope") != "qualification_q":
        raise ValueError("authorization scope is not qualification_q")

    expected_systems = sorted(DEFAULT_SYSTEM_IDS)
    bundle_systems = bundle_manifest.get("system_ids")
    if not isinstance(bundle_systems, list) or sorted(bundle_systems) != expected_systems:
        raise ValueError("input bundle system set differs from qualification registry")
    system_authorizations = authorization.get("systems")
    if not isinstance(system_authorizations, list):
        raise ValueError("authorization systems must be a list")
    by_system = {
        item.get("system_id"): item
        for item in system_authorizations
        if isinstance(item, dict) and item.get("system_id")
    }
    if sorted(by_system) != expected_systems:
        raise ValueError("authorization system set differs from qualification registry")

    tasks = bundle_manifest.get("tasks")
    if not isinstance(tasks, list) or len(tasks) != 50:
        raise ValueError("qualification input bundle must contain exactly 50 tasks")
    entries: List[Dict[str, Any]] = []
    seen_indices = set()
    system_counts = {system_id: 0 for system_id in expected_systems}
    for task_position, task in enumerate(tasks):
        if not isinstance(task, dict):
            raise ValueError("task entry must be an object")
        idx = task.get("idx")
        if not isinstance(idx, int) or isinstance(idx, bool) or idx in seen_indices:
            raise ValueError("task idx values must be unique integers")
        seen_indices.add(idx)
        order = task.get("system_order")
        if not isinstance(order, list) or sorted(order) != expected_systems:
            raise ValueError("each task must schedule every registered system exactly once")
        for within_task_position, system_id in enumerate(order):
            system_auth = by_system[system_id]
            sequence = len(entries)
            entries.append(
                {
                    "sequence": sequence,
                    "task_position": task_position,
                    "within_task_position": within_task_position,
                    "idx": idx,
                    "problem_id": task.get("problem_id"),
                    "problem_sha256": task.get("problem_sha256"),
                    "stratum": task.get("stratum"),
                    "system_id": system_id,
                    "episode_timeout_s": system_auth.get("episode_timeout_s"),
                    "output_relative_path": "%s/%s.json" % (system_id, idx),
                }
            )
            system_counts[system_id] += 1

    if len(entries) != 150 or any(count != 50 for count in system_counts.values()):
        raise ValueError("qualification plan must contain 150 matched episodes")

    systems = []
    for system_id in expected_systems:
        item = by_system[system_id]
        timeout = item.get("episode_timeout_s")
        episode_cap = item.get("episode_cap")
        wall_cap = item.get("summed_wall_time_cap_s")
        maximum_timeout_envelope = (
            timeout * episode_cap
            if isinstance(timeout, int)
            and not isinstance(timeout, bool)
            and isinstance(episode_cap, int)
            and not isinstance(episode_cap, bool)
            else None
        )
        systems.append(
            {
                "system_id": system_id,
                "episode_count": system_counts[system_id],
                "episode_cap": episode_cap,
                "episode_timeout_s": timeout,
                "summed_wall_time_cap_s": wall_cap,
                "maximum_timeout_envelope_s": maximum_timeout_envelope,
                "wall_cap_can_stop_before_episode_cap": bool(
                    isinstance(maximum_timeout_envelope, int)
                    and isinstance(wall_cap, int)
                    and wall_cap < maximum_timeout_envelope
                ),
            }
        )

    plan = {
        "format": "mathaudit-qualification-execution-plan-v0.1",
        "authorization_id": authorization.get("authorization_id"),
        "authorization_status": authorization.get("status"),
        "runnable": authorization.get("status") == "authorized",
        "schedule_seed": bundle_manifest.get("schedule_seed"),
        "input_bundle_sha256": bundle_manifest.get("bundle_sha256"),
        "task_count": len(tasks),
        "episode_count": len(entries),
        "systems": systems,
        "entries": entries,
        "notes": [
            "Provider-free plan compilation only; runnable=true is necessary but not sufficient.",
            "Actual execution additionally requires a green qualification preflight and local credentials.",
            "Task-major blocked order follows the frozen per-task system_order permutations.",
        ],
    }
    plan["plan_sha256"] = sha256_json(copy.deepcopy(plan))
    return plan


def verify_qualification_execution_plan(
    plan: Dict[str, Any],
    bundle_manifest: Dict[str, Any],
    authorization: Dict[str, Any],
    *,
    source_plan: Optional[Dict[str, Any]] = None,
    source_state: Optional[Dict[str, Any]] = None,
    replacement_inventory: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Require byte-semantic equality with a freshly compiled frozen plan."""

    if plan.get("format") == "mathaudit-qualification-execution-plan-v0.1":
        expected = compile_qualification_execution_plan(bundle_manifest, authorization)
    elif plan.get("format") in {
        "mathaudit-qualification-execution-plan-v0.2",
        "mathaudit-qualification-execution-plan-v0.3",
        "mathaudit-qualification-execution-plan-v0.4",
    }:
        if source_plan is None or source_state is None:
            raise ValueError("continuation plan verification requires source plan and state")
        expected = compile_qualification_continuation_plan(
            bundle_manifest,
            authorization,
            source_plan=source_plan,
            source_state=source_state,
        )
    elif plan.get("format") == "mathaudit-qualification-execution-plan-v0.5":
        if source_plan is None or replacement_inventory is None:
            raise ValueError(
                "replacement plan verification requires the source schedule plan and replacement inventory"
            )
        expected = compile_qualification_replacement_plan(
            bundle_manifest,
            authorization,
            source_plan=source_plan,
            replacement_inventory=replacement_inventory,
        )
    else:
        raise ValueError("unsupported qualification execution plan format")
    if plan != expected:
        legacy = copy.deepcopy(expected)
        legacy["notes"] = copy.deepcopy(LEGACY_CONTINUATION_NOTES)
        legacy.pop("plan_sha256", None)
        observed = copy.deepcopy(plan)
        observed.pop("plan_sha256", None)
        legacy_match = (
            plan.get("format") in {
                "mathaudit-qualification-execution-plan-v0.2",
                "mathaudit-qualification-execution-plan-v0.3",
                "mathaudit-qualification-execution-plan-v0.4",
            }
            and observed == legacy
        )
        if not legacy_match:
            raise ValueError("execution plan differs from deterministic compilation")
        _verify_embedded_hash(plan, "plan_sha256", "execution plan")
    return {
        "plan_sha256": plan["plan_sha256"],
        "task_count": plan["task_count"],
        "episode_count": plan["episode_count"],
        "runnable": plan["runnable"],
    }


def _verify_embedded_hash(payload: Dict[str, Any], field: str, label: str) -> None:
    claimed = payload.get(field)
    candidate = copy.deepcopy(payload)
    candidate.pop(field, None)
    if claimed != sha256_json(candidate):
        raise ValueError("%s self-hash mismatch" % label)


def compile_qualification_continuation_plan(
    bundle_manifest: Dict[str, Any],
    authorization: Dict[str, Any],
    *,
    source_plan: Dict[str, Any],
    source_state: Dict[str, Any],
) -> Dict[str, Any]:
    """Compile a continuation suffix, optionally deferring the failed boundary."""

    if bundle_manifest.get("format") != "mathaudit-input-bundle-v0.1":
        raise ValueError("unsupported input-bundle manifest format")
    if authorization.get("format") not in CONTINUATION_AUTHORIZATION_FORMATS:
        raise ValueError("continuation authorization format is required")
    if authorization.get("scope") != "qualification_q":
        raise ValueError("authorization scope is not qualification_q")
    source_format = source_plan.get("format")
    if source_format not in {
        "mathaudit-qualification-execution-plan-v0.1",
        "mathaudit-qualification-execution-plan-v0.2",
        "mathaudit-qualification-execution-plan-v0.3",
        "mathaudit-qualification-execution-plan-v0.4",
    }:
        raise ValueError("source plan must be a qualification plan or continuation plan")
    _verify_embedded_hash(source_plan, "plan_sha256", "source plan")
    verify_executor_state_self_hash(source_state)

    continuation = authorization.get("continuation")
    if not isinstance(continuation, dict):
        raise ValueError("continuation provenance is required")
    if continuation.get("source_authorization_id") != source_state.get("authorization_id"):
        raise ValueError("continuation source authorization mismatch")
    if continuation.get("source_plan_sha256") != source_plan.get("plan_sha256"):
        raise ValueError("continuation source plan mismatch")
    if continuation.get("source_state_sha256") != source_state.get("state_sha256"):
        raise ValueError("continuation source state mismatch")
    if source_state.get("plan_sha256") != source_plan.get("plan_sha256"):
        raise ValueError("source state/plan mismatch")
    if source_plan.get("input_bundle_sha256") != bundle_manifest.get("bundle_sha256"):
        raise ValueError("source plan input bundle mismatch")
    if source_state.get("status") != "stopped_failure":
        raise ValueError("continuation source state must be stopped_failure")
    if source_state.get("current_episodes"):
        raise ValueError("continuation source state contains unfinished episodes")

    skip_failed_boundary = authorization.get("format") in {
        SKIP_BOUNDARY_CONTINUATION_AUTHORIZATION_FORMAT,
        CONTINUE_AFTER_FAILURE_AUTHORIZATION_FORMAT,
    }
    prefix = continuation.get("completed_prefix_episode_count")
    restart = continuation.get("restart_sequence")
    if not isinstance(prefix, int) or isinstance(prefix, bool):
        raise ValueError("continuation prefix is invalid")
    if skip_failed_boundary:
        if restart != prefix + 1:
            raise ValueError("skip-boundary continuation restart must follow the failed boundary")
        if continuation.get("deferred_replacement_count") != 1:
            raise ValueError("skip-boundary continuation must defer one replacement episode")
        deferred_sequence = continuation.get("deferred_replacement_sequence")
        if authorization.get("format") == SKIP_BOUNDARY_CONTINUATION_AUTHORIZATION_FORMAT:
            deferred_ok = deferred_sequence == prefix
        else:
            deferred_ok = (
                isinstance(deferred_sequence, int)
                and not isinstance(deferred_sequence, bool)
                and 1 <= deferred_sequence < prefix
            )
        if not deferred_ok:
            raise ValueError("skip-boundary continuation replacement sequence mismatch")
    elif restart != prefix:
        raise ValueError("continuation prefix/restart is invalid")
    source_entries = source_plan.get("entries")
    source_episodes = source_state.get("episodes")
    if not isinstance(source_entries, list) or not source_entries:
        raise ValueError("source plan entries must be a non-empty list")
    source_sequences = [item.get("sequence") for item in source_entries]
    if source_format == "mathaudit-qualification-execution-plan-v0.1":
        source_start = 0
    else:
        source_continuation = source_plan.get("continuation")
        if not isinstance(source_continuation, dict):
            raise ValueError("source continuation plan lacks provenance")
        source_start = source_continuation.get("restart_sequence")
        if source_continuation.get("final_target_episode_count") != 150:
            raise ValueError("source continuation target is not 150")
    if not isinstance(source_start, int) or isinstance(source_start, bool):
        raise ValueError("source plan restart boundary is invalid")
    if source_sequences != list(range(source_start, 150)):
        raise ValueError("source plan must cover a contiguous suffix through sequence 149")
    if restart < source_start:
        raise ValueError("continuation restart precedes the source plan")
    relative_restart = restart - source_start
    expected_state_length = relative_restart if skip_failed_boundary else relative_restart + 1
    if not isinstance(source_episodes, list) or len(source_episodes) != expected_state_length:
        raise ValueError("source state does not end at the registered continuation boundary")
    completed_positions = relative_restart - 1 if skip_failed_boundary else relative_restart
    for position in range(completed_positions):
        observed = source_episodes[position]
        expected = source_entries[position]
        aligned = (
            observed.get("sequence") == expected.get("sequence")
            and observed.get("system_id") == expected.get("system_id")
            and observed.get("idx") == expected.get("idx")
        )
        attempts = observed.get("attempts")
        # v0.4 deliberately continues past terminal single-episode failures.
        # Such failures are part of the inherited prefix and must not be
        # mistaken for an unfinished episode; only completed records require
        # a valid full trace.
        prefix_valid = (
            aligned
            and isinstance(attempts, list)
            and bool(attempts)
            and (
                authorization.get("format") == CONTINUE_AFTER_FAILURE_AUTHORIZATION_FORMAT
                or (
                    observed.get("status") == "completed"
                    and attempts[-1].get("valid_full_trace") is True
                )
            )
        )
        if not prefix_valid:
            raise ValueError(
                "source state completed prefix is invalid at sequence %d"
                % expected.get("sequence")
            )
    failed_position = relative_restart - 1 if skip_failed_boundary else relative_restart
    failed = source_episodes[failed_position]
    expected_failed_sequence = restart - 1 if skip_failed_boundary else restart
    if (
        failed.get("sequence") != expected_failed_sequence
        or failed.get("status") == "completed"
    ):
        raise ValueError("source state restart boundary is not a failed episode")

    systems = authorization.get("systems")
    if not isinstance(systems, list):
        raise ValueError("authorization systems must be a list")
    by_system = {
        item.get("system_id"): item
        for item in systems
        if isinstance(item, dict) and item.get("system_id")
    }
    if sorted(by_system) != sorted(DEFAULT_SYSTEM_IDS):
        raise ValueError("authorization system set differs from qualification registry")

    entries: List[Dict[str, Any]] = []
    system_counts = {system_id: 0 for system_id in DEFAULT_SYSTEM_IDS}
    for source_entry in source_entries[relative_restart:]:
        entry = copy.deepcopy(source_entry)
        system_id = str(entry["system_id"])
        entry["episode_timeout_s"] = by_system[system_id].get("episode_timeout_s")
        entries.append(entry)
        system_counts[system_id] += 1
    expected_entry_count = 150 - prefix - (1 if skip_failed_boundary else 0)
    if len(entries) != expected_entry_count:
        raise ValueError("continuation entry count differs from target minus prefix")
    if authorization.get("total_budget", {}).get("episode_cap") != len(entries):
        raise ValueError("continuation authorization total episode cap mismatch")

    plan_systems = []
    for system_id in sorted(DEFAULT_SYSTEM_IDS):
        item = by_system[system_id]
        episode_count = system_counts[system_id]
        if item.get("episode_cap") != episode_count:
            raise ValueError("continuation system episode cap mismatch: %s" % system_id)
        timeout = item.get("episode_timeout_s")
        wall_cap = item.get("summed_wall_time_cap_s")
        maximum_timeout_envelope = (
            timeout * episode_count
            if isinstance(timeout, int)
            and not isinstance(timeout, bool)
            and isinstance(episode_count, int)
            else None
        )
        plan_systems.append(
            {
                "system_id": system_id,
                "episode_count": episode_count,
                "episode_cap": item.get("episode_cap"),
                "episode_timeout_s": timeout,
                "summed_wall_time_cap_s": wall_cap,
                "maximum_timeout_envelope_s": maximum_timeout_envelope,
                "wall_cap_can_stop_before_episode_cap": bool(
                    isinstance(maximum_timeout_envelope, int)
                    and isinstance(wall_cap, int)
                    and wall_cap < maximum_timeout_envelope
                ),
            }
        )

    plan = {
        "format": (
            "mathaudit-qualification-execution-plan-v0.4"
            if authorization.get("format") == CONTINUE_AFTER_FAILURE_AUTHORIZATION_FORMAT
            else "mathaudit-qualification-execution-plan-v0.3"
            if skip_failed_boundary
            else "mathaudit-qualification-execution-plan-v0.2"
        ),
        "authorization_id": authorization.get("authorization_id"),
        "authorization_status": authorization.get("status"),
        "runnable": authorization.get("status") == "authorized",
        "schedule_seed": bundle_manifest.get("schedule_seed"),
        "input_bundle_sha256": bundle_manifest.get("bundle_sha256"),
        "task_count": len(bundle_manifest.get("tasks") or []),
        "episode_count": len(entries),
        "continuation": copy.deepcopy(continuation),
        "systems": plan_systems,
        "entries": entries,
        "notes": [
            "Provider-free continuation compilation only; runnable=true is necessary but not sufficient.",
            "Sequences before restart_sequence are inherited only through the outcome-blind source lineage.",
            (
                "The failed boundary sequence is explicitly deferred for a separately authorized replacement; "
                "this plan contains only the unattempted suffix."
                if skip_failed_boundary
                else "The failed boundary sequence is rerun; no failed or incomplete trace is inherited."
            ),
        ],
    }
    if plan["task_count"] != 50:
        raise ValueError("qualification input bundle must contain exactly 50 tasks")
    plan["plan_sha256"] = sha256_json(copy.deepcopy(plan))
    return plan


def compile_qualification_replacement_plan(
    bundle_manifest: Dict[str, Any],
    authorization: Dict[str, Any],
    *,
    source_plan: Dict[str, Any],
    replacement_inventory: Dict[str, Any],
) -> Dict[str, Any]:
    """Compile separately authorized replacements for exact missing schedule slots."""

    if bundle_manifest.get("format") != "mathaudit-input-bundle-v0.1":
        raise ValueError("unsupported input-bundle manifest format")
    if authorization.get("format") != REPLACEMENT_AUTHORIZATION_FORMAT:
        raise ValueError("replacement authorization format is required")
    if authorization.get("scope") != "qualification_q":
        raise ValueError("authorization scope is not qualification_q")
    if source_plan.get("format") != "mathaudit-qualification-execution-plan-v0.1":
        raise ValueError("replacement source schedule must be a full qualification plan")
    _verify_embedded_hash(source_plan, "plan_sha256", "source schedule plan")
    if source_plan.get("input_bundle_sha256") != bundle_manifest.get("bundle_sha256"):
        raise ValueError("replacement source schedule input bundle mismatch")
    source_entries = source_plan.get("entries")
    if (
        not isinstance(source_entries, list)
        or len(source_entries) != 150
        or [entry.get("sequence") for entry in source_entries] != list(range(150))
    ):
        raise ValueError("replacement source schedule must contain sequences 0 through 149")

    inventory_format = replacement_inventory.get("format")
    if inventory_format not in REPLACEMENT_INVENTORY_FORMATS:
        raise ValueError("unsupported replacement inventory format")
    _verify_embedded_hash(replacement_inventory, "inventory_sha256", "replacement inventory")
    if replacement_inventory.get("outcome_blind") is not True:
        raise ValueError("replacement inventory must be outcome-blind")
    if replacement_inventory.get("contains_prompt_or_response_text") is not False:
        raise ValueError("replacement inventory must not contain prompt or response text")

    replacement = authorization.get("replacement")
    if not isinstance(replacement, dict):
        raise ValueError("replacement provenance is required")
    if replacement.get("source_schedule_plan_sha256") != source_plan.get("plan_sha256"):
        raise ValueError("replacement source schedule plan mismatch")
    if replacement.get("source_inventory_sha256") != replacement_inventory.get(
        "inventory_sha256"
    ):
        raise ValueError("replacement inventory mismatch")
    lineage = replacement_inventory.get("lineage_states")
    source_run_id = replacement.get("source_run_id") or "q11"
    source_state_sha256 = replacement.get("source_state_sha256") or replacement.get(
        "source_q11_state_sha256"
    )
    source_lineage = [
        item
        for item in lineage or []
        if isinstance(item, dict) and item.get("run_id") == source_run_id
    ]
    if len(source_lineage) != 1 or source_state_sha256 != source_lineage[0].get("state_sha256"):
        raise ValueError("replacement Q11 state provenance mismatch")

    sequences = replacement.get("replacement_sequences")
    inventory_slots = replacement_inventory.get("missing_slots")
    inventory_sequences = [
        item.get("sequence") for item in inventory_slots or [] if isinstance(item, dict)
    ]
    if sequences != inventory_sequences:
        raise ValueError("replacement sequences differ from the frozen missing-slot inventory")
    expected_complete_count = 150 - len(sequences or [])
    if replacement_inventory.get("complete_full_trace_slot_count") != expected_complete_count:
        raise ValueError("replacement inventory complete-slot count mismatch")
    if replacement_inventory.get("missing_full_trace_slot_count") != len(sequences or []):
        raise ValueError("replacement inventory missing-slot count mismatch")
    if replacement.get("complete_slot_count_before_replacement") != expected_complete_count:
        raise ValueError("replacement authorization prior complete-slot count mismatch")
    if replacement.get("final_target_episode_count") != 150:
        raise ValueError("replacement final target must be 150")

    systems = authorization.get("systems")
    if not isinstance(systems, list):
        raise ValueError("authorization systems must be a list")
    by_system = {
        item.get("system_id"): item
        for item in systems
        if isinstance(item, dict) and item.get("system_id")
    }
    if sorted(by_system) != sorted(DEFAULT_SYSTEM_IDS):
        raise ValueError("authorization system set differs from qualification registry")

    entries: List[Dict[str, Any]] = []
    system_counts = {system_id: 0 for system_id in DEFAULT_SYSTEM_IDS}
    for slot in inventory_slots or []:
        sequence = slot.get("sequence")
        if not isinstance(sequence, int) or isinstance(sequence, bool):
            raise ValueError("replacement inventory sequence is invalid")
        source_entry = source_entries[sequence]
        if (
            slot.get("system_id") != source_entry.get("system_id")
            or slot.get("idx") != source_entry.get("idx")
            or slot.get("status") == "completed"
            or slot.get("valid_full_trace") is not False
        ):
            raise ValueError("replacement inventory slot does not match the frozen schedule")
        entry = copy.deepcopy(source_entry)
        system_id = str(entry["system_id"])
        entry["episode_timeout_s"] = by_system[system_id].get("episode_timeout_s")
        entries.append(entry)
        system_counts[system_id] += 1

    if authorization.get("total_budget", {}).get("episode_cap") != len(entries):
        raise ValueError("replacement authorization total episode cap mismatch")
    if [entry["sequence"] for entry in entries] != sequences:
        raise ValueError("replacement plan sequence order is not deterministic")

    plan_systems = []
    for system_id in sorted(DEFAULT_SYSTEM_IDS):
        item = by_system[system_id]
        episode_count = system_counts[system_id]
        if item.get("episode_cap") != episode_count:
            raise ValueError("replacement system episode cap mismatch: %s" % system_id)
        timeout = item.get("episode_timeout_s")
        wall_cap = item.get("summed_wall_time_cap_s")
        maximum_timeout_envelope = (
            timeout * episode_count
            if isinstance(timeout, int)
            and not isinstance(timeout, bool)
            and isinstance(episode_count, int)
            else None
        )
        plan_systems.append(
            {
                "system_id": system_id,
                "episode_count": episode_count,
                "episode_cap": item.get("episode_cap"),
                "episode_timeout_s": timeout,
                "summed_wall_time_cap_s": wall_cap,
                "maximum_timeout_envelope_s": maximum_timeout_envelope,
                "wall_cap_can_stop_before_episode_cap": bool(
                    isinstance(maximum_timeout_envelope, int)
                    and isinstance(wall_cap, int)
                    and wall_cap < maximum_timeout_envelope
                ),
            }
        )

    notes = [
        "Provider-free replacement compilation only; runnable=true is necessary but not sufficient.",
        "Only the exact missing sequence set frozen in the outcome-blind inventory is scheduled.",
        "Each replacement is one separately authorized episode; no failed or partial trace is inherited.",
    ]
    if inventory_format == "mathaudit-q11-postrun-replacement-inventory-v0.1":
        notes[1] = "Only the exact missing sequence set frozen after Q11 is scheduled."
    plan = {
        "format": "mathaudit-qualification-execution-plan-v0.5",
        "authorization_id": authorization.get("authorization_id"),
        "authorization_status": authorization.get("status"),
        "runnable": authorization.get("status") == "authorized",
        "schedule_seed": bundle_manifest.get("schedule_seed"),
        "input_bundle_sha256": bundle_manifest.get("bundle_sha256"),
        "task_count": len(bundle_manifest.get("tasks") or []),
        "episode_count": len(entries),
        "replacement": copy.deepcopy(replacement),
        "systems": plan_systems,
        "entries": entries,
        "notes": notes,
    }
    if plan["task_count"] != 50:
        raise ValueError("qualification input bundle must contain exactly 50 tasks")
    plan["plan_sha256"] = sha256_json(copy.deepcopy(plan))
    return plan
