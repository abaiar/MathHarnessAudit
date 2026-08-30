"""Outcome-blind deterministic sampling and identifier-only public manifests."""

from __future__ import annotations

import hashlib
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .hashing import sha256_json, sha256_text


@dataclass(frozen=True)
class SampleCandidate:
    record: Dict[str, Any]
    source_index: int
    source_id: Optional[str]
    problem_hash: str
    record_hash: str
    difficulty: Optional[float]
    balance_group: str


def canonical_problem_text(value: Any) -> str:
    text = unicodedata.normalize("NFC", str(value or ""))
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _nested_value(record: Dict[str, Any], field: Optional[str]) -> Any:
    if not field:
        return None
    value: Any = record
    for part in field.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def _balance_group(record: Dict[str, Any], field: Optional[str], depth: Optional[int]) -> str:
    value = _nested_value(record, field)
    if value is None:
        return "unclassified"
    if isinstance(value, list):
        value = value[0] if value else "unclassified"
    text = str(value).strip() or "unclassified"
    if depth is not None and "->" in text:
        parts = [part.strip() for part in text.split("->") if part.strip()]
        text = " -> ".join(parts[:depth])
    return text


def _difficulty(record: Dict[str, Any], field: Optional[str]) -> Optional[float]:
    value = _nested_value(record, field)
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("difficulty field %r is not numeric: %r" % (field, value)) from exc


def _rank(seed: int, *parts: str) -> str:
    return sha256_text("\x1f".join([str(seed), *parts]))


def _allocation(
    pools: Dict[str, Sequence[SampleCandidate]],
    count: int,
    *,
    mode: str,
    seed: int,
) -> Dict[str, int]:
    groups = sorted(pools)
    if not groups:
        return {}
    if mode not in {"equal", "proportional"}:
        raise ValueError("balance mode must be 'equal' or 'proportional'")
    if mode == "equal":
        base, remainder = divmod(count, len(groups))
        ordered = sorted(groups, key=lambda item: _rank(seed, "group", item))
        requested = {group: base + int(group in ordered[:remainder]) for group in groups}
    else:
        total = sum(len(pools[group]) for group in groups)
        raw = {group: count * len(pools[group]) / total for group in groups}
        requested = {group: int(raw[group]) for group in groups}
        remainder = count - sum(requested.values())
        ordered = sorted(
            groups,
            key=lambda item: (-(raw[item] - requested[item]), _rank(seed, "group", item)),
        )
        for group in ordered[:remainder]:
            requested[group] += 1

    allocated = {group: min(requested[group], len(pools[group])) for group in groups}
    missing = count - sum(allocated.values())
    while missing:
        available = [group for group in groups if allocated[group] < len(pools[group])]
        if not available:
            raise ValueError("not enough eligible records for requested sample")
        available.sort(key=lambda item: _rank(seed, "refill", str(allocated[item]), item))
        for group in available:
            if not missing:
                break
            allocated[group] += 1
            missing -= 1
    return allocated


def select_sample(
    records: Iterable[Dict[str, Any]],
    *,
    dataset_id: str,
    count: int,
    seed: int,
    statement_field: str = "problem",
    id_field: Optional[str] = None,
    difficulty_field: Optional[str] = None,
    difficulty_gt: Optional[float] = None,
    difficulty_le: Optional[float] = None,
    balance_field: Optional[str] = None,
    balance_depth: Optional[int] = None,
    balance_mode: str = "equal",
) -> Tuple[List[SampleCandidate], Dict[str, Any]]:
    """Select records without using answer, solution, or system-outcome fields."""

    if count < 1:
        raise ValueError("count must be positive")
    candidates: List[SampleCandidate] = []
    statement_counts: Counter[str] = Counter()
    source_id_counts: Counter[str] = Counter()
    input_count = 0
    for index, record in enumerate(records):
        input_count += 1
        statement = canonical_problem_text(_nested_value(record, statement_field))
        if not statement:
            raise ValueError("record %d has no statement in %s" % (index, statement_field))
        problem_hash = sha256_text(statement)
        statement_counts[problem_hash] += 1
        source_value = _nested_value(record, id_field)
        source_id = None if source_value is None else str(source_value)
        if source_id is not None:
            source_id_counts[source_id] += 1
        difficulty = _difficulty(record, difficulty_field)
        candidates.append(
            SampleCandidate(
                record=record,
                source_index=index,
                source_id=source_id,
                problem_hash=problem_hash,
                record_hash=sha256_json(record),
                difficulty=difficulty,
                balance_group=_balance_group(record, balance_field, balance_depth),
            )
        )

    duplicate_source_ids = sorted(
        source_id for source_id, frequency in source_id_counts.items() if frequency > 1
    )
    if duplicate_source_ids:
        preview = ", ".join(repr(value) for value in duplicate_source_ids[:3])
        suffix = "" if len(duplicate_source_ids) <= 3 else ", ..."
        raise ValueError(
            "id field %r must be unique; duplicate source ID(s): %s%s"
            % (id_field, preview, suffix)
        )

    duplicate_hashes = {value for value, frequency in statement_counts.items() if frequency > 1}
    unique = [item for item in candidates if item.problem_hash not in duplicate_hashes]
    eligible = []
    missing_difficulty = 0
    for item in unique:
        if difficulty_gt is not None or difficulty_le is not None:
            if item.difficulty is None:
                missing_difficulty += 1
                continue
            if difficulty_gt is not None and item.difficulty <= difficulty_gt:
                continue
            if difficulty_le is not None and item.difficulty > difficulty_le:
                continue
        eligible.append(item)
    if len(eligible) < count:
        raise ValueError("requested %d records but only %d are eligible" % (count, len(eligible)))

    pools: Dict[str, List[SampleCandidate]] = defaultdict(list)
    for item in eligible:
        pools[item.balance_group].append(item)
    allocation = _allocation(pools, count, mode=balance_mode, seed=seed)
    selected: List[SampleCandidate] = []
    for group, amount in allocation.items():
        ranked = sorted(
            pools[group],
            key=lambda item: _rank(seed, dataset_id, group, item.problem_hash, item.record_hash),
        )
        selected.extend(ranked[:amount])
    selected.sort(key=lambda item: _rank(seed, "final", dataset_id, item.problem_hash))
    diagnostics = {
        "input_records": input_count,
        "non_null_source_ids": sum(source_id_counts.values()),
        "unique_non_null_source_ids": len(source_id_counts),
        "unique_problem_hashes": len(statement_counts),
        "duplicate_problem_groups_excluded": len(duplicate_hashes),
        "records_excluded_for_duplicate_problem": sum(statement_counts[item] for item in duplicate_hashes),
        "records_missing_required_difficulty": missing_difficulty,
        "eligible_records": len(eligible),
        "eligible_by_balance_group": dict(sorted(Counter(item.balance_group for item in eligible).items())),
        "selected_by_balance_group": dict(sorted(Counter(item.balance_group for item in selected).items())),
    }
    return selected, diagnostics


def public_sample_manifest(
    selected: Sequence[SampleCandidate],
    *,
    source_path: Path,
    dataset_id: str,
    dataset_version: Optional[str],
    stratum: str,
    seed: int,
    selection_config: Dict[str, Any],
    diagnostics: Dict[str, Any],
) -> Dict[str, Any]:
    entries = []
    for item in selected:
        stable_suffix = item.source_id or item.problem_hash
        entries.append(
            {
                "problem_id": "%s#%s" % (dataset_id, stable_suffix),
                "source_record_id": item.source_id,
                "problem_sha256": item.problem_hash,
                "record_sha256": item.record_hash,
                "stratum": stratum,
                "difficulty": item.difficulty,
                "balance_group": item.balance_group,
            }
        )
    manifest = {
        "format": "mathaudit-sample-manifest-v0.1",
        "dataset_id": dataset_id,
        "dataset_version": dataset_version,
        "stratum": stratum,
        "source_file_sha256": file_sha256(source_path),
        "selection_seed": seed,
        "selection_config": selection_config,
        "diagnostics": diagnostics,
        "selected": entries,
        "privacy": {
            "contains_problem_text": False,
            "contains_answers_or_solutions": False,
            "official_dataset_download_required": True,
        },
    }
    manifest["manifest_sha256"] = sha256_json(manifest)
    return manifest


def verify_sample_manifest_hash(manifest: Dict[str, Any]) -> bool:
    """Verify the self-hash of a public sample manifest without mutating it."""

    recorded = manifest.get("manifest_sha256")
    if not isinstance(recorded, str):
        return False
    hash_input = dict(manifest)
    hash_input.pop("manifest_sha256", None)
    return recorded == sha256_json(hash_input)
