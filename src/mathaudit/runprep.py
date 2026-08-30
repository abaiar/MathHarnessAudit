"""Compile frozen private samples into gold-separated matched-run inputs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Sequence

from .hashing import sha256_json, sha256_text
from .ingest import iter_payloads
from .sampling import canonical_problem_text, file_sha256, verify_sample_manifest_hash

FORBIDDEN_SOLVER_FIELDS = {
    "answer",
    "gold",
    "gold_answer",
    "ground_truth",
    "solution",
    "reference_answer",
    "reference_solution",
    "proof",
}


def _nested_value(record: Dict[str, Any], field: str) -> Any:
    value: Any = record
    for part in field.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def _write_jsonl(path: Path, rows: Sequence[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _load_private_sample(path: Path, statement_field: str) -> Dict[str, Dict[str, Any]]:
    records: Dict[str, Dict[str, Any]] = {}
    for record, locator in iter_payloads(path):
        audit = record.get("_mathaudit")
        if not isinstance(audit, dict):
            raise ValueError("%s has no _mathaudit sampling metadata" % locator)
        statement = canonical_problem_text(_nested_value(record, statement_field))
        actual_problem_hash = sha256_text(statement)
        if audit.get("problem_sha256") != actual_problem_hash:
            raise ValueError("%s problem hash does not match _mathaudit metadata" % locator)
        original = dict(record)
        original.pop("_mathaudit", None)
        actual_record_hash = sha256_json(original)
        if audit.get("record_sha256") != actual_record_hash:
            raise ValueError("%s record hash does not match _mathaudit metadata" % locator)
        if actual_problem_hash in records:
            raise ValueError("%s repeats a private problem hash" % locator)
        records[actual_problem_hash] = record
    return records


def prepare_matched_run_inputs(
    *,
    private_samples: Sequence[Path],
    public_manifests: Sequence[Path],
    output_dir: Path,
    system_ids: Sequence[str],
    schedule_seed: int,
) -> Dict[str, Any]:
    """Prepare solver-visible and audit-only inputs without contacting a model."""

    if len(private_samples) != len(public_manifests) or not private_samples:
        raise ValueError("provide one private sample for each public manifest")
    systems = sorted(set(system_ids))
    if not systems or len(systems) != len(system_ids):
        raise ValueError("system IDs must be non-empty and unique")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError("output directory must be absent or empty: %s" % output_dir)

    competition_rows: List[Dict[str, Any]] = []
    mathgoal_rows: List[Dict[str, Any]] = []
    audit_rows: List[Dict[str, Any]] = []
    task_entries: List[Dict[str, Any]] = []
    seen_problem_hashes = set()
    source_manifests = []

    for private_path, manifest_path in zip(
        private_samples, public_manifests, strict=True
    ):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict) or not verify_sample_manifest_hash(manifest):
            raise ValueError("invalid sample manifest self-hash: %s" % manifest_path)
        config = manifest.get("selection_config") or {}
        statement_field = str(config.get("statement_field") or "problem")
        private_records = _load_private_sample(private_path, statement_field)
        selected = manifest.get("selected")
        if not isinstance(selected, list) or not selected:
            raise ValueError("sample manifest has no selected entries: %s" % manifest_path)
        selected_hashes = {str(entry.get("problem_sha256")) for entry in selected}
        if selected_hashes != set(private_records):
            raise ValueError("private sample and public manifest problem hashes differ")

        source_manifests.append(
            {
                "dataset_id": manifest["dataset_id"],
                "dataset_version": manifest.get("dataset_version"),
                "stratum": manifest["stratum"],
                "manifest_sha256": manifest["manifest_sha256"],
            }
        )
        for entry in selected:
            problem_hash = str(entry["problem_sha256"])
            if problem_hash in seen_problem_hashes:
                raise ValueError("problem appears in more than one stratum: %s" % problem_hash)
            seen_problem_hashes.add(problem_hash)
            private_record = private_records[problem_hash]
            original = dict(private_record)
            original.pop("_mathaudit", None)
            if sha256_json(original) != entry["record_sha256"]:
                raise ValueError("public record hash does not match private record: %s" % problem_hash)
            statement = canonical_problem_text(_nested_value(private_record, statement_field))
            index = len(task_entries)
            public_problem_id = str(entry["problem_id"])

            competition_rows.append({"idx": index, "problem": statement})
            mathgoal_rows.append({"id": str(index), "question": statement})
            audit_row = dict(private_record)
            audit_row.update(
                {
                    "idx": index,
                    "public_problem_id": public_problem_id,
                    "source_dataset_id": manifest["dataset_id"],
                    "source_dataset_version": manifest.get("dataset_version"),
                    "source_stratum": manifest["stratum"],
                }
            )
            audit_rows.append(audit_row)
            system_order = sorted(
                systems,
                key=lambda system_id: sha256_text(
                    "\x1f".join(
                        [str(schedule_seed), "system-order", public_problem_id, system_id]
                    )
                ),
            )
            task_entries.append(
                {
                    "idx": index,
                    "problem_id": public_problem_id,
                    "problem_sha256": problem_hash,
                    "record_sha256": entry["record_sha256"],
                    "stratum": manifest["stratum"],
                    "system_order": system_order,
                }
            )

    competition_path = output_dir / "solver_visible" / "competition.jsonl"
    mathgoal_path = output_dir / "solver_visible" / "mathgoal.jsonl"
    audit_path = output_dir / "audit_only" / "problems.jsonl"
    _write_jsonl(competition_path, competition_rows)
    _write_jsonl(mathgoal_path, mathgoal_rows)
    _write_jsonl(audit_path, audit_rows)

    bundle = {
        "format": "mathaudit-input-bundle-v0.1",
        "schedule_seed": schedule_seed,
        "system_ids": systems,
        "source_manifests": source_manifests,
        "task_count": len(task_entries),
        "tasks": task_entries,
        "files": {
            "solver_visible_competition": {
                "relative_path": "solver_visible/competition.jsonl",
                "sha256": file_sha256(competition_path),
                "contains_gold": False,
            },
            "solver_visible_mathgoal": {
                "relative_path": "solver_visible/mathgoal.jsonl",
                "sha256": file_sha256(mathgoal_path),
                "contains_gold": False,
            },
            "audit_only_problems": {
                "relative_path": "audit_only/problems.jsonl",
                "sha256": file_sha256(audit_path),
                "contains_gold": True,
            },
        },
        "privacy": {
            "manifest_contains_problem_text": False,
            "solver_visible_files_contain_answers_or_solutions": False,
            "audit_only_file_must_remain_private": True,
        },
    }
    bundle["bundle_sha256"] = sha256_json(bundle)
    manifest_path = output_dir / "input_bundle_manifest.json"
    manifest_path.write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return bundle


def verify_input_bundle(output_dir: Path) -> Dict[str, Any]:
    """Verify bundle self-hash, file hashes, row counts, joins, and gold separation."""

    manifest_path = output_dir / "input_bundle_manifest.json"
    bundle = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(bundle, dict) or bundle.get("format") != "mathaudit-input-bundle-v0.1":
        raise ValueError("not a mathaudit-input-bundle-v0.1 manifest")
    recorded_hash = bundle.get("bundle_sha256")
    hash_input = dict(bundle)
    hash_input.pop("bundle_sha256", None)
    if not isinstance(recorded_hash, str) or recorded_hash != sha256_json(hash_input):
        raise ValueError("input bundle self-hash mismatch")
    task_count = bundle.get("task_count")
    tasks = bundle.get("tasks")
    systems = set(bundle.get("system_ids") or [])
    if not isinstance(task_count, int) or not isinstance(tasks, list) or len(tasks) != task_count:
        raise ValueError("input bundle task count mismatch")
    if {task.get("idx") for task in tasks} != set(range(task_count)):
        raise ValueError("input bundle task indices are not exactly 0..task_count-1")
    if any(set(task.get("system_order") or []) != systems for task in tasks):
        raise ValueError("a task system order is not a permutation of system_ids")

    expected_keys = {
        "solver_visible_competition": {"idx", "problem"},
        "solver_visible_mathgoal": {"id", "question"},
    }
    root = output_dir.resolve()
    files = bundle.get("files")
    if not isinstance(files, dict):
        raise ValueError("input bundle has no file inventory")
    for role, entry in files.items():
        if not isinstance(entry, dict):
            raise ValueError("invalid file inventory entry: %s" % role)
        path = (root / str(entry.get("relative_path") or "")).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError("file escapes the input bundle root: %s" % path) from exc
        if not path.is_file() or file_sha256(path) != entry.get("sha256"):
            raise ValueError("file hash mismatch: %s" % role)
        rows = [payload for payload, _ in iter_payloads(path)]
        if len(rows) != task_count:
            raise ValueError("file row count mismatch: %s" % role)
        if entry.get("contains_gold") is False:
            for row in rows:
                forbidden = FORBIDDEN_SOLVER_FIELDS.intersection(row)
                if forbidden:
                    raise ValueError("solver-visible file exposes gold field(s): %s" % sorted(forbidden))
            if role in expected_keys and any(set(row) != expected_keys[role] for row in rows):
                raise ValueError("solver-visible file has unexpected fields: %s" % role)
    return {
        "task_count": task_count,
        "file_count": len(files),
        "bundle_sha256": recorded_hash,
    }
