# SPDX-License-Identifier: MIT

"""Outcome-blind assembly of a stopped prefix and its authorized continuation."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple

from .executor_state import verify_executor_state_self_hash
from .hashing import sha256_json
from .io import read_episodes, write_episodes
from .models import Episode

COMPOSITE_FORMAT = "mathaudit-qualification-composite-v0.1"
LINEAGE_COMPOSITE_FORMAT = "mathaudit-qualification-composite-v0.2"
REPLACEMENT_COMPOSITE_FORMAT = "mathaudit-qualification-composite-v0.3"
SYSTEM_IDS = ("mathrouter", "icma", "mathgoal")
PLAN_ENTRY_IDENTITY_FIELDS = (
    "sequence",
    "task_position",
    "within_task_position",
    "idx",
    "problem_id",
    "problem_sha256",
    "stratum",
    "system_id",
    "output_relative_path",
)


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


def _verify_embedded_hash(payload: Dict[str, Any], field: str, label: str) -> None:
    claimed = payload.get(field)
    candidate = copy.deepcopy(payload)
    candidate.pop(field, None)
    if claimed != sha256_json(candidate):
        raise ValueError("%s self-hash mismatch" % label)


def _canonical_paths(closeout_dir: Path) -> Tuple[Dict[str, Any], Dict[str, Path]]:
    closeout_path = closeout_dir / "closeout-manifest.json"
    closeout = _load_object(closeout_path)
    if closeout.get("format") != "mathaudit-qualification-closeout-v0.1":
        raise ValueError("unsupported qualification closeout")
    _verify_embedded_hash(closeout, "closeout_sha256", "qualification closeout")
    if closeout.get("outcome_blind") is not True:
        raise ValueError("qualification closeout is not outcome-blind")
    if closeout.get("contains_prompt_or_response_text") is not False:
        raise ValueError("qualification closeout manifest text policy violation")
    health = closeout.get("health_report") or {}
    health_path = closeout_dir / str(health.get("relative_path") or "")
    if not health_path.is_file() or _file_sha256(health_path) != health.get("sha256"):
        raise ValueError("qualification closeout health artifact mismatch")

    manifest_rows = closeout.get("final_run_manifests")
    if not isinstance(manifest_rows, list):
        raise ValueError("qualification closeout run manifests are missing")
    by_system = {row.get("system_id"): row for row in manifest_rows if isinstance(row, dict)}
    if set(by_system) != set(SYSTEM_IDS):
        raise ValueError("qualification closeout system set mismatch")
    canonical: Dict[str, Path] = {}
    for system_id in SYSTEM_IDS:
        manifest_row = by_system[system_id]
        manifest_path = closeout_dir / str(manifest_row["relative_path"])
        if _file_sha256(manifest_path) != manifest_row["sha256"]:
            raise ValueError("qualification final run manifest hash mismatch")
        manifest = _load_object(manifest_path)
        artifacts = manifest.get("artifacts") or []
        matches = [row for row in artifacts if row.get("role") == "canonical_episodes"]
        if len(matches) != 1:
            raise ValueError("qualification canonical artifact registration mismatch")
        artifact = matches[0]
        canonical_path = closeout_dir / str(artifact["relative_path"])
        if not canonical_path.is_file() or _file_sha256(canonical_path) != artifact["sha256"]:
            raise ValueError("qualification canonical artifact hash mismatch")
        canonical[system_id] = canonical_path
    return closeout, canonical


def _episode_map(
    canonical_paths: Dict[str, Path],
) -> Dict[Tuple[str, str], Episode]:
    result: Dict[Tuple[str, str], Episode] = {}
    for system_id in SYSTEM_IDS:
        for episode in read_episodes(canonical_paths[system_id]):
            key = (episode.problem.problem_id, episode.system.system_id)
            if episode.system.system_id != system_id:
                raise ValueError("canonical episode system mismatch")
            if key in result:
                raise ValueError("duplicate canonical problem/system pair")
            if episode.labels:
                raise ValueError("outcome-blind canonical episode already contains labels")
            result[key] = episode
    return result


def _expected_keys(entries: Iterable[Dict[str, Any]]) -> set:
    return {(str(row["problem_id"]), str(row["system_id"])) for row in entries}


def assemble_qualification_composite(
    *,
    source_plan_path: Path,
    prefix_state_path: Path,
    continuation_plan_path: Path,
    continuation_state_path: Path,
    prefix_closeout_dir: Path,
    continuation_closeout_dir: Path,
    output_dir: Path,
) -> Dict[str, Any]:
    """Assemble exactly 150 complete canonical traces without scoring them."""

    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError("composite output directory must be absent or empty")
    source_plan = _load_object(source_plan_path)
    continuation_plan = _load_object(continuation_plan_path)
    _verify_embedded_hash(source_plan, "plan_sha256", "source plan")
    _verify_embedded_hash(continuation_plan, "plan_sha256", "continuation plan")
    if source_plan.get("format") != "mathaudit-qualification-execution-plan-v0.1":
        raise ValueError("source plan must be full qualification v0.1")
    if continuation_plan.get("format") != "mathaudit-qualification-execution-plan-v0.2":
        raise ValueError("continuation plan must be v0.2")
    source_entries = source_plan.get("entries")
    continuation_entries = continuation_plan.get("entries")
    if not isinstance(source_entries, list) or len(source_entries) != 150:
        raise ValueError("source plan must contain 150 entries")
    continuation = continuation_plan.get("continuation") or {}
    prefix_count = continuation.get("completed_prefix_episode_count")
    restart = continuation.get("restart_sequence")
    if not isinstance(prefix_count, int) or restart != prefix_count:
        raise ValueError("continuation boundary is invalid")
    if continuation.get("source_plan_sha256") != source_plan.get("plan_sha256"):
        raise ValueError("continuation does not reference the source plan")
    if not isinstance(continuation_entries, list) or [
        row.get("sequence") for row in continuation_entries
    ] != list(range(restart, 150)):
        raise ValueError("continuation plan does not cover the exact frozen suffix")
    for observed, expected in zip(continuation_entries, source_entries[restart:], strict=True):
        for field in (
            "sequence",
            "task_position",
            "within_task_position",
            "idx",
            "problem_id",
            "problem_sha256",
            "stratum",
            "system_id",
            "output_relative_path",
        ):
            if observed.get(field) != expected.get(field):
                raise ValueError("continuation plan suffix drift: %s" % field)

    prefix_state = _load_object(prefix_state_path)
    continuation_state = _load_object(continuation_state_path)
    verify_executor_state_self_hash(prefix_state)
    verify_executor_state_self_hash(continuation_state)
    if continuation.get("source_state_sha256") != prefix_state.get("state_sha256"):
        raise ValueError("continuation does not reference the prefix state")
    if prefix_state.get("current_episodes") or continuation_state.get("current_episodes"):
        raise ValueError("composite source contains unfinished episodes")
    prefix_rows = prefix_state.get("episodes")
    suffix_rows = continuation_state.get("episodes")
    if not isinstance(prefix_rows, list) or len(prefix_rows) != restart + 1:
        raise ValueError("prefix state does not end at the restart boundary")
    if [row.get("sequence") for row in prefix_rows[:prefix_count]] != list(
        range(prefix_count)
    ) or any(row.get("status") != "completed" for row in prefix_rows[:prefix_count]):
        raise ValueError("prefix state does not contain the complete inherited prefix")
    if prefix_rows[restart].get("status") == "completed":
        raise ValueError("restart boundary was not failed in the prefix state")
    if continuation_state.get("status") != "completed":
        raise ValueError("continuation state is not completed")
    if (
        not isinstance(suffix_rows, list)
        or [row.get("sequence") for row in suffix_rows] != list(range(restart, 150))
        or any(row.get("status") != "completed" for row in suffix_rows)
    ):
        raise ValueError("continuation state is not the complete registered suffix")

    prefix_closeout, prefix_paths = _canonical_paths(prefix_closeout_dir)
    suffix_closeout, suffix_paths = _canonical_paths(continuation_closeout_dir)
    if prefix_closeout.get("plan_sha256") != source_plan.get("plan_sha256"):
        raise ValueError("prefix closeout plan mismatch")
    if suffix_closeout.get("plan_sha256") != continuation_plan.get("plan_sha256"):
        raise ValueError("continuation closeout plan mismatch")
    prefix_episodes = _episode_map(prefix_paths)
    suffix_episodes = _episode_map(suffix_paths)
    prefix_expected = _expected_keys(source_entries[:prefix_count])
    suffix_expected = _expected_keys(continuation_entries)
    if set(prefix_episodes) != prefix_expected:
        raise ValueError("prefix canonical set differs from inherited complete entries")
    if set(suffix_episodes) != suffix_expected:
        raise ValueError("continuation canonical set differs from suffix entries")
    if set(prefix_episodes) & set(suffix_episodes):
        raise ValueError("prefix and continuation canonical sets overlap")
    combined = {**prefix_episodes, **suffix_episodes}
    if set(combined) != _expected_keys(source_entries):
        raise ValueError("composite does not contain the full 150-entry source plan")

    output_dir.mkdir(parents=True, exist_ok=True)
    canonical_dir = output_dir / "canonical"
    index_rows: List[Dict[str, Any]] = []
    artifacts: List[Dict[str, Any]] = []
    source_role_by_key = {key: "prefix" for key in prefix_episodes}
    source_role_by_key.update({key: "continuation" for key in suffix_episodes})
    for system_id in SYSTEM_IDS:
        entries = [row for row in source_entries if row["system_id"] == system_id]
        episodes = [combined[(row["problem_id"], system_id)] for row in entries]
        path = canonical_dir / (system_id + ".jsonl")
        write_episodes(path, episodes)
        artifacts.append(
            {
                "system_id": system_id,
                "relative_path": path.relative_to(output_dir).as_posix(),
                "sha256": _file_sha256(path),
                "records": len(episodes),
                "private": True,
            }
        )
        for line_number, (entry, episode) in enumerate(
            zip(entries, episodes, strict=True), start=1
        ):
            key = (entry["problem_id"], system_id)
            index_rows.append(
                {
                    "sequence": entry["sequence"],
                    "task_position": entry["task_position"],
                    "problem_id": entry["problem_id"],
                    "system_id": system_id,
                    "episode_id": episode.episode_id,
                    "source_role": source_role_by_key[key],
                    "canonical_relative_path": path.relative_to(output_dir).as_posix(),
                    "canonical_line_number": line_number,
                }
            )
    index_rows.sort(key=lambda row: int(row["sequence"]))
    index = {
        "format": "mathaudit-qualification-composite-index-v0.1",
        "records": index_rows,
    }
    index["index_sha256"] = sha256_json(index)
    index_path = output_dir / "sequence-index.json"
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest = {
        "format": COMPOSITE_FORMAT,
        "source_plan_sha256": source_plan["plan_sha256"],
        "continuation_plan_sha256": continuation_plan["plan_sha256"],
        "prefix": {
            "authorization_id": prefix_closeout["authorization_id"],
            "closeout_sha256": prefix_closeout["closeout_sha256"],
            "completed_sequence_start": 0,
            "completed_sequence_end": prefix_count - 1,
            "episode_count": prefix_count,
        },
        "continuation": {
            "authorization_id": suffix_closeout["authorization_id"],
            "closeout_sha256": suffix_closeout["closeout_sha256"],
            "completed_sequence_start": restart,
            "completed_sequence_end": 149,
            "episode_count": len(continuation_entries),
        },
        "episode_count": 150,
        "system_episode_counts": {system_id: 50 for system_id in SYSTEM_IDS},
        "canonical_artifacts": artifacts,
        "sequence_index": {
            "relative_path": "sequence-index.json",
            "sha256": _file_sha256(index_path),
            "records": 150,
        },
        "outcome_blind": True,
        "correctness_aggregates_computed": False,
        "contains_prompt_or_response_text": False,
    }
    manifest["composite_sha256"] = sha256_json(manifest)
    manifest_path = output_dir / "composite-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def assemble_qualification_lineage_composite(
    *,
    plan_paths: Sequence[Path],
    state_paths: Sequence[Path],
    closeout_dirs: Sequence[Path],
    output_dir: Path,
) -> Dict[str, Any]:
    """Assemble exact-150 traces from an outcome-blind continuation lineage."""

    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError("composite output directory must be absent or empty")
    if not (len(plan_paths) == len(state_paths) == len(closeout_dirs) and len(plan_paths) >= 2):
        raise ValueError("lineage requires equal plan/state/closeout lists of length at least two")

    plans = [_load_object(path) for path in plan_paths]
    states = [_load_object(path) for path in state_paths]
    for position, plan in enumerate(plans):
        _verify_embedded_hash(plan, "plan_sha256", "lineage plan %d" % position)
    for state in states:
        verify_executor_state_self_hash(state)

    root_plan = plans[0]
    if root_plan.get("format") != "mathaudit-qualification-execution-plan-v0.1":
        raise ValueError("lineage root must be the full qualification v0.1 plan")
    root_entries = root_plan.get("entries")
    if not isinstance(root_entries, list) or [row.get("sequence") for row in root_entries] != list(
        range(150)
    ):
        raise ValueError("lineage root plan must contain sequences 0-149")

    starts: List[int] = []
    for position, plan in enumerate(plans):
        entries = plan.get("entries")
        if not isinstance(entries, list) or not entries:
            raise ValueError("lineage plan entries must be non-empty")
        if position == 0:
            start = 0
        else:
            if plan.get("format") != "mathaudit-qualification-execution-plan-v0.2":
                raise ValueError("non-root lineage plans must be continuation v0.2")
            continuation = plan.get("continuation")
            if not isinstance(continuation, dict):
                raise ValueError("lineage continuation provenance is missing")
            start = continuation.get("restart_sequence")
            if not isinstance(start, int) or isinstance(start, bool):
                raise ValueError("lineage continuation restart is invalid")
            previous_plan = plans[position - 1]
            previous_state = states[position - 1]
            if (
                continuation.get("source_authorization_id")
                != previous_state.get("authorization_id")
                or continuation.get("source_plan_sha256") != previous_plan.get("plan_sha256")
                or continuation.get("source_state_sha256") != previous_state.get("state_sha256")
                or continuation.get("completed_prefix_episode_count") != start
                or continuation.get("final_target_episode_count") != 150
            ):
                raise ValueError("lineage continuation provenance mismatch")
        if [row.get("sequence") for row in entries] != list(range(start, 150)):
            raise ValueError("lineage plan does not cover its exact suffix")
        for observed in entries:
            expected = root_entries[int(observed["sequence"])]
            for field in PLAN_ENTRY_IDENTITY_FIELDS:
                if observed.get(field) != expected.get(field):
                    raise ValueError("lineage plan drift: %s" % field)
        starts.append(start)
    if starts != sorted(starts):
        raise ValueError("lineage restart boundaries are not monotonic")

    combined: Dict[Tuple[str, str], Episode] = {}
    source_by_sequence: Dict[int, Tuple[int, str]] = {}
    lineage_rows: List[Dict[str, Any]] = []
    for position, (plan, state, closeout_dir) in enumerate(
        zip(plans, states, closeout_dirs, strict=True)
    ):
        start = starts[position]
        end = starts[position + 1] - 1 if position + 1 < len(starts) else 149
        terminal_boundary = end + 1 if position + 1 < len(starts) else None
        if (
            state.get("plan_sha256") != plan.get("plan_sha256")
            or state.get("authorization_id") != plan.get("authorization_id")
            or state.get("current_episodes")
        ):
            raise ValueError("lineage executor state does not match its plan")
        state_rows = state.get("episodes")
        if not isinstance(state_rows, list):
            raise ValueError("lineage executor episodes must be a list")
        expected_state_sequences = list(range(start, end + 1))
        if terminal_boundary is not None:
            expected_state_sequences.append(terminal_boundary)
            if state.get("status") != "stopped_failure":
                raise ValueError("non-final lineage state must be stopped_failure")
        elif state.get("status") != "completed":
            raise ValueError("final lineage state must be completed")
        if [row.get("sequence") for row in state_rows] != expected_state_sequences:
            raise ValueError("lineage executor state sequence coverage mismatch")
        for row in state_rows:
            sequence = int(row["sequence"])
            expected = root_entries[sequence]
            if row.get("system_id") != expected.get("system_id") or row.get("idx") != expected.get(
                "idx"
            ):
                raise ValueError("lineage executor state entry mismatch")
            if sequence <= end:
                attempts = row.get("attempts")
                if (
                    row.get("status") != "completed"
                    or not isinstance(attempts, list)
                    or not attempts
                    or attempts[-1].get("valid_full_trace") is not True
                ):
                    raise ValueError("lineage inherited episode is not a complete full trace")
            elif row.get("status") == "completed":
                raise ValueError("lineage restart boundary was not failed")

        closeout, canonical_paths = _canonical_paths(closeout_dir)
        if closeout.get("plan_sha256") != plan.get("plan_sha256") or closeout.get(
            "authorization_id"
        ) != plan.get("authorization_id"):
            raise ValueError("lineage closeout does not match its plan")
        episodes = _episode_map(canonical_paths)
        expected_entries = root_entries[start : end + 1]
        expected_keys = _expected_keys(expected_entries)
        if set(episodes) != expected_keys:
            raise ValueError("lineage canonical set differs from its completed segment")
        if set(combined) & set(episodes):
            raise ValueError("lineage canonical segments overlap")
        combined.update(episodes)
        for sequence in range(start, end + 1):
            source_by_sequence[sequence] = (position, str(closeout["authorization_id"]))
        lineage_rows.append(
            {
                "position": position,
                "authorization_id": closeout["authorization_id"],
                "plan_sha256": plan["plan_sha256"],
                "state_sha256": state["state_sha256"],
                "closeout_sha256": closeout["closeout_sha256"],
                "executor_terminal_status": state["status"],
                "completed_sequence_start": start,
                "completed_sequence_end": end if end >= start else None,
                "episode_count": end - start + 1,
            }
        )

    if set(combined) != _expected_keys(root_entries) or set(source_by_sequence) != set(range(150)):
        raise ValueError("lineage composite does not contain the exact full plan")

    output_dir.mkdir(parents=True, exist_ok=True)
    canonical_dir = output_dir / "canonical"
    index_rows: List[Dict[str, Any]] = []
    artifacts: List[Dict[str, Any]] = []
    for system_id in SYSTEM_IDS:
        entries = [row for row in root_entries if row["system_id"] == system_id]
        episodes = [combined[(row["problem_id"], system_id)] for row in entries]
        path = canonical_dir / (system_id + ".jsonl")
        write_episodes(path, episodes)
        artifacts.append(
            {
                "system_id": system_id,
                "relative_path": path.relative_to(output_dir).as_posix(),
                "sha256": _file_sha256(path),
                "records": len(episodes),
                "private": True,
            }
        )
        for line_number, (entry, episode) in enumerate(
            zip(entries, episodes, strict=True), start=1
        ):
            segment_position, authorization_id = source_by_sequence[int(entry["sequence"])]
            index_rows.append(
                {
                    "sequence": entry["sequence"],
                    "task_position": entry["task_position"],
                    "problem_id": entry["problem_id"],
                    "system_id": system_id,
                    "episode_id": episode.episode_id,
                    "source_segment_position": segment_position,
                    "source_authorization_id": authorization_id,
                    "canonical_relative_path": path.relative_to(output_dir).as_posix(),
                    "canonical_line_number": line_number,
                }
            )
    index_rows.sort(key=lambda row: int(row["sequence"]))
    index = {
        "format": "mathaudit-qualification-composite-index-v0.2",
        "records": index_rows,
    }
    index["index_sha256"] = sha256_json(index)
    index_path = output_dir / "sequence-index.json"
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest = {
        "format": LINEAGE_COMPOSITE_FORMAT,
        "source_plan_sha256": root_plan["plan_sha256"],
        "lineage": lineage_rows,
        "episode_count": 150,
        "system_episode_counts": {system_id: 50 for system_id in SYSTEM_IDS},
        "canonical_artifacts": artifacts,
        "sequence_index": {
            "relative_path": "sequence-index.json",
            "sha256": _file_sha256(index_path),
            "records": 150,
        },
        "outcome_blind": True,
        "correctness_aggregates_computed": False,
        "contains_prompt_or_response_text": False,
    }
    manifest["composite_sha256"] = sha256_json(manifest)
    (output_dir / "composite-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def assemble_qualification_replacement_composite(
    *,
    root_plan_path: Path,
    base_plan_paths: Sequence[Path],
    base_state_paths: Sequence[Path],
    base_closeout_dirs: Sequence[Path],
    replacement_plan_path: Path,
    replacement_state_path: Path,
    replacement_closeout_dir: Path,
    replacement_inventory_path: Path,
    output_dir: Path,
) -> Dict[str, Any]:
    """Overlay complete, authorized replacements onto a frozen incomplete lineage."""

    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError("replacement composite output directory must be absent or empty")
    if not (
        len(base_plan_paths) == len(base_state_paths) == len(base_closeout_dirs) and base_plan_paths
    ):
        raise ValueError("replacement composite requires equal non-empty base lineage lists")

    root_plan = _load_object(root_plan_path)
    _verify_embedded_hash(root_plan, "plan_sha256", "replacement root plan")
    if root_plan.get("format") != "mathaudit-qualification-execution-plan-v0.1":
        raise ValueError("replacement root must be the full qualification v0.1 plan")
    root_entries = root_plan.get("entries")
    if not isinstance(root_entries, list) or [row.get("sequence") for row in root_entries] != list(
        range(150)
    ):
        raise ValueError("replacement root plan must contain sequences 0-149")
    root_by_sequence = {int(row["sequence"]): row for row in root_entries}

    inventory = _load_object(replacement_inventory_path)
    if inventory.get("format") not in {
        "mathaudit-q11-postrun-replacement-inventory-v0.1",
        "mathaudit-q12-postrun-replacement-inventory-v0.1",
        "mathaudit-q13-postrun-replacement-inventory-v0.1",
    }:
        raise ValueError("unsupported replacement inventory")
    _verify_embedded_hash(inventory, "inventory_sha256", "replacement inventory")
    if (
        inventory.get("outcome_blind") is not True
        or inventory.get("contains_prompt_or_response_text") is not False
    ):
        raise ValueError("replacement inventory violates outcome-blind policy")
    missing_slots = inventory.get("missing_slots")
    if not isinstance(missing_slots, list):
        raise ValueError("replacement inventory missing slots are absent")
    missing_sequences = [row.get("sequence") for row in missing_slots]
    if (
        missing_sequences != sorted(set(missing_sequences))
        or inventory.get("complete_full_trace_slot_count") != 150 - len(missing_sequences)
        or inventory.get("missing_full_trace_slot_count") != len(missing_sequences)
    ):
        raise ValueError("replacement inventory coverage counts are inconsistent")

    base_plans = [_load_object(path) for path in base_plan_paths]
    base_states = [_load_object(path) for path in base_state_paths]
    inventory_lineage = inventory.get("lineage_states") or []
    if [row.get("state_sha256") for row in inventory_lineage] != [
        state.get("state_sha256") for state in base_states
    ]:
        raise ValueError("replacement inventory does not freeze the supplied base lineage")

    combined: Dict[Tuple[str, str], Episode] = {}
    source_by_sequence: Dict[int, Tuple[str, str]] = {}
    base_complete_sequences: set[int] = set()
    lineage_rows: List[Dict[str, Any]] = []
    for position, (plan, state, closeout_dir) in enumerate(
        zip(base_plans, base_states, base_closeout_dirs, strict=True)
    ):
        _verify_embedded_hash(plan, "plan_sha256", "replacement base plan %d" % position)
        verify_executor_state_self_hash(state)
        if plan.get("format") not in {
            "mathaudit-qualification-execution-plan-v0.1",
            "mathaudit-qualification-execution-plan-v0.2",
            "mathaudit-qualification-execution-plan-v0.3",
            "mathaudit-qualification-execution-plan-v0.4",
            "mathaudit-qualification-execution-plan-v0.5",
        }:
            raise ValueError("unsupported replacement base plan format")
        if (
            state.get("plan_sha256") != plan.get("plan_sha256")
            or state.get("authorization_id") != plan.get("authorization_id")
            or state.get("current_episodes")
        ):
            raise ValueError("replacement base state does not match its plan")
        plan_entries = plan.get("entries")
        if not isinstance(plan_entries, list) or not plan_entries:
            raise ValueError("replacement base plan entries are missing")
        plan_by_sequence = {int(row["sequence"]): row for row in plan_entries}
        if len(plan_by_sequence) != len(plan_entries):
            raise ValueError("replacement base plan contains duplicate sequences")
        for observed in plan_entries:
            expected = root_by_sequence.get(int(observed["sequence"]))
            if expected is None or any(
                observed.get(field) != expected.get(field) for field in PLAN_ENTRY_IDENTITY_FIELDS
            ):
                raise ValueError("replacement base plan drifts from the root schedule")

        state_rows = state.get("episodes")
        if not isinstance(state_rows, list):
            raise ValueError("replacement base state episodes are missing")
        completed_entries = []
        for row in state_rows:
            sequence = row.get("sequence")
            if sequence not in plan_by_sequence:
                raise ValueError("replacement base state sequence is outside its plan")
            expected = root_by_sequence[int(sequence)]
            if row.get("system_id") != expected.get("system_id") or row.get("idx") != expected.get(
                "idx"
            ):
                raise ValueError("replacement base state entry drifts from the root schedule")
            attempts = row.get("attempts")
            if row.get("status") == "completed":
                if (
                    not isinstance(attempts, list)
                    or not attempts
                    or attempts[-1].get("valid_full_trace") is not True
                ):
                    raise ValueError("replacement base completed episode lacks a full trace")
                if int(sequence) in base_complete_sequences:
                    raise ValueError("replacement base lineage contains duplicate complete slots")
                base_complete_sequences.add(int(sequence))
                completed_entries.append(expected)

        closeout, canonical_paths = _canonical_paths(closeout_dir)
        if closeout.get("plan_sha256") != plan.get("plan_sha256") or closeout.get(
            "authorization_id"
        ) != plan.get("authorization_id"):
            raise ValueError("replacement base closeout does not match its plan")
        episodes = _episode_map(canonical_paths)
        if set(episodes) != _expected_keys(completed_entries):
            raise ValueError("replacement base canonical set differs from completed state rows")
        for entry in completed_entries:
            key = (str(entry["problem_id"]), str(entry["system_id"]))
            if key in combined:
                raise ValueError("replacement base canonical segments overlap")
            combined[key] = episodes[key]
            source_by_sequence[int(entry["sequence"])] = (
                "base",
                str(closeout["authorization_id"]),
            )
        lineage_rows.append(
            {
                "position": position,
                "authorization_id": closeout["authorization_id"],
                "plan_sha256": plan["plan_sha256"],
                "state_sha256": state["state_sha256"],
                "closeout_sha256": closeout["closeout_sha256"],
                "executor_terminal_status": state["status"],
                "complete_episode_count": len(completed_entries),
            }
        )

    if sorted(set(range(150)) - base_complete_sequences) != missing_sequences:
        raise ValueError("replacement base lineage missing set differs from the frozen inventory")

    replacement_plan = _load_object(replacement_plan_path)
    replacement_state = _load_object(replacement_state_path)
    _verify_embedded_hash(replacement_plan, "plan_sha256", "replacement plan")
    verify_executor_state_self_hash(replacement_state)
    if replacement_plan.get("format") != "mathaudit-qualification-execution-plan-v0.5":
        raise ValueError("replacement plan must be v0.5")
    replacement = replacement_plan.get("replacement") or {}
    replacement_entries = replacement_plan.get("entries")
    if (
        replacement.get("source_schedule_plan_sha256") != root_plan.get("plan_sha256")
        or replacement.get("source_inventory_sha256") != inventory.get("inventory_sha256")
        or replacement.get("replacement_sequences") != missing_sequences
        or not isinstance(replacement_entries, list)
        or [row.get("sequence") for row in replacement_entries] != missing_sequences
    ):
        raise ValueError("replacement plan provenance or sequence set mismatch")
    for observed in replacement_entries:
        expected = root_by_sequence[int(observed["sequence"])]
        if any(observed.get(field) != expected.get(field) for field in PLAN_ENTRY_IDENTITY_FIELDS):
            raise ValueError("replacement plan drifts from the root schedule")
    if (
        replacement_state.get("plan_sha256") != replacement_plan.get("plan_sha256")
        or replacement_state.get("authorization_id") != replacement_plan.get("authorization_id")
        or replacement_state.get("status") != "completed"
        or replacement_state.get("current_episodes")
    ):
        raise ValueError("replacement executor state is not a completed matching run")
    replacement_rows = replacement_state.get("episodes")
    if (
        not isinstance(replacement_rows, list)
        or [row.get("sequence") for row in replacement_rows] != missing_sequences
    ):
        raise ValueError("replacement executor state sequence set mismatch")
    for row in replacement_rows:
        expected = root_by_sequence[int(row["sequence"])]
        attempts = row.get("attempts")
        if (
            row.get("system_id") != expected.get("system_id")
            or row.get("idx") != expected.get("idx")
            or row.get("status") != "completed"
            or not isinstance(attempts, list)
            or not attempts
            or attempts[-1].get("valid_full_trace") is not True
        ):
            raise ValueError("replacement episode is not a complete full trace")

    replacement_closeout, replacement_paths = _canonical_paths(replacement_closeout_dir)
    if replacement_closeout.get("plan_sha256") != replacement_plan.get(
        "plan_sha256"
    ) or replacement_closeout.get("authorization_id") != replacement_plan.get("authorization_id"):
        raise ValueError("replacement closeout does not match its plan")
    replacement_episodes = _episode_map(replacement_paths)
    if set(replacement_episodes) != _expected_keys(replacement_entries):
        raise ValueError("replacement canonical set differs from the exact replacement plan")
    for entry in replacement_entries:
        key = (str(entry["problem_id"]), str(entry["system_id"]))
        if key in combined:
            raise ValueError("replacement canonical set overlaps an already complete base slot")
        combined[key] = replacement_episodes[key]
        source_by_sequence[int(entry["sequence"])] = (
            "replacement",
            str(replacement_closeout["authorization_id"]),
        )

    if set(combined) != _expected_keys(root_entries) or set(source_by_sequence) != set(range(150)):
        raise ValueError("replacement composite does not contain the exact full plan")

    output_dir.mkdir(parents=True, exist_ok=True)
    canonical_dir = output_dir / "canonical"
    index_rows: List[Dict[str, Any]] = []
    artifacts: List[Dict[str, Any]] = []
    for system_id in SYSTEM_IDS:
        entries = [row for row in root_entries if row["system_id"] == system_id]
        episodes = [combined[(str(row["problem_id"]), system_id)] for row in entries]
        path = canonical_dir / (system_id + ".jsonl")
        write_episodes(path, episodes)
        artifacts.append(
            {
                "system_id": system_id,
                "relative_path": path.relative_to(output_dir).as_posix(),
                "sha256": _file_sha256(path),
                "records": len(episodes),
                "private": True,
            }
        )
        for line_number, (entry, episode) in enumerate(
            zip(entries, episodes, strict=True), start=1
        ):
            source_role, authorization_id = source_by_sequence[int(entry["sequence"])]
            index_rows.append(
                {
                    "sequence": entry["sequence"],
                    "task_position": entry["task_position"],
                    "problem_id": entry["problem_id"],
                    "system_id": system_id,
                    "episode_id": episode.episode_id,
                    "source_role": source_role,
                    "source_authorization_id": authorization_id,
                    "canonical_relative_path": path.relative_to(output_dir).as_posix(),
                    "canonical_line_number": line_number,
                }
            )
    index_rows.sort(key=lambda row: int(row["sequence"]))
    index = {
        "format": "mathaudit-qualification-composite-index-v0.3",
        "records": index_rows,
    }
    index["index_sha256"] = sha256_json(index)
    index_path = output_dir / "sequence-index.json"
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest = {
        "format": REPLACEMENT_COMPOSITE_FORMAT,
        "source_plan_sha256": root_plan["plan_sha256"],
        "base_lineage": lineage_rows,
        "replacement": {
            "authorization_id": replacement_closeout["authorization_id"],
            "plan_sha256": replacement_plan["plan_sha256"],
            "state_sha256": replacement_state["state_sha256"],
            "closeout_sha256": replacement_closeout["closeout_sha256"],
            "inventory_sha256": inventory["inventory_sha256"],
            "sequences": missing_sequences,
            "episode_count": len(missing_sequences),
        },
        "episode_count": 150,
        "system_episode_counts": {system_id: 50 for system_id in SYSTEM_IDS},
        "canonical_artifacts": artifacts,
        "sequence_index": {
            "relative_path": "sequence-index.json",
            "sha256": _file_sha256(index_path),
            "records": 150,
        },
        "outcome_blind": True,
        "correctness_aggregates_computed": False,
        "contains_prompt_or_response_text": False,
    }
    manifest["composite_sha256"] = sha256_json(manifest)
    (output_dir / "composite-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest
