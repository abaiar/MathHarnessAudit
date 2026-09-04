# SPDX-License-Identifier: MIT

"""Deterministic scoring gate for a complete qualification composite."""

from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

from .adjudication import adjudication_episode_content_sha256
from .hashing import sha256_json
from .io import read_episodes, write_episodes
from .models import Episode
from .scoring import SCORER_NAME, SCORER_VERSION, score_episode

SCORING_FORMAT = "mathaudit-qualification-scoring-v0.1"
ADJUDICATION_INPUT_FORMAT = "mathaudit-qualification-adjudication-input-v0.1"
ADJUDICATED_SCORING_FORMAT = "mathaudit-qualification-scoring-v0.2"
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


def _verify_hash(payload: Dict[str, Any], field: str, label: str) -> None:
    claimed = payload.get(field)
    candidate = copy.deepcopy(payload)
    candidate.pop(field, None)
    if claimed != sha256_json(candidate):
        raise ValueError("%s self-hash mismatch" % label)


def load_qualification_scoring(
    scoring_dir: Path,
    *,
    allowed_formats: Sequence[str] = (SCORING_FORMAT, ADJUDICATED_SCORING_FORMAT),
) -> Tuple[Dict[str, Any], Dict[str, List[Episode]]]:
    """Verify and load an exact-150 deterministic or adjudicated scoring set."""

    manifest_path = scoring_dir / "scoring-manifest.json"
    manifest = _load_object(manifest_path)
    if manifest.get("format") not in set(allowed_formats):
        raise ValueError("unsupported qualification scoring manifest")
    _verify_hash(manifest, "scoring_sha256", "qualification scoring")
    if (
        manifest.get("episode_count") != 150
        or manifest.get("system_episode_counts") != {"mathrouter": 50, "icma": 50, "mathgoal": 50}
        or manifest.get("correctness_labels_computed") is not True
    ):
        raise ValueError("qualification scoring is incomplete")
    rows = manifest.get("scored_artifacts")
    if not isinstance(rows, list):
        raise ValueError("qualification scored artifacts are missing")
    by_system = {row.get("system_id"): row for row in rows if isinstance(row, dict)}
    if set(by_system) != set(SYSTEM_IDS):
        raise ValueError("qualification scored system set mismatch")
    episodes_by_system: Dict[str, List[Episode]] = {}
    seen_ids = set()
    for system_id in SYSTEM_IDS:
        row = by_system[system_id]
        path = scoring_dir / str(row.get("relative_path") or "")
        if (
            not path.is_file()
            or _file_sha256(path) != row.get("sha256")
            or row.get("episodes") != 50
        ):
            raise ValueError("qualification scored artifact mismatch")
        episodes = list(read_episodes(path))
        if (
            len(episodes) != 50
            or any(episode.system.system_id != system_id for episode in episodes)
            or any(not episode.labels for episode in episodes)
        ):
            raise ValueError("qualification scored artifact content mismatch")
        ids = [episode.episode_id for episode in episodes]
        if len(ids) != len(set(ids)) or seen_ids.intersection(ids):
            raise ValueError("qualification scored episode identifiers are not unique")
        seen_ids.update(ids)
        episodes_by_system[system_id] = episodes
    return manifest, episodes_by_system


def _ordered_episodes(episodes_by_system: Dict[str, List[Episode]]) -> List[Episode]:
    return [episode for system_id in SYSTEM_IDS for episode in episodes_by_system[system_id]]


def prepare_qualification_adjudication(*, scoring_dir: Path, output_dir: Path) -> Dict[str, Any]:
    """Create one exact-150, hash-linked input for the blinded rater workflow."""

    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError("qualification adjudication input must be absent or empty")
    scoring, by_system = load_qualification_scoring(scoring_dir, allowed_formats=(SCORING_FORMAT,))
    episodes = _ordered_episodes(by_system)
    output_dir.mkdir(parents=True, exist_ok=True)
    episodes_path = output_dir / "scored-episodes.jsonl"
    write_episodes(episodes_path, episodes)
    manifest = {
        "format": ADJUDICATION_INPUT_FORMAT,
        "source_plan_sha256": scoring["source_plan_sha256"],
        "scoring_sha256": scoring["scoring_sha256"],
        "scoring_manifest_raw_sha256": _file_sha256(scoring_dir / "scoring-manifest.json"),
        "episode_count": 150,
        "system_episode_counts": {system_id: 50 for system_id in SYSTEM_IDS},
        "episode_content_sha256": adjudication_episode_content_sha256(episodes),
        "scored_episodes": {
            "relative_path": "scored-episodes.jsonl",
            "sha256": _file_sha256(episodes_path),
            "episodes": 150,
            "private": True,
        },
    }
    manifest["manifest_sha256"] = sha256_json(manifest)
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def _without_labels(episode: Episode) -> Dict[str, Any]:
    payload = episode.model_dump(mode="json")
    payload["labels"] = []
    return payload


def freeze_qualification_adjudication(
    *,
    scoring_dir: Path,
    adjudication_input_dir: Path,
    adjudication_dir: Path,
    output_dir: Path,
    guide_version: str,
    guide_sha256: str,
) -> Dict[str, Any]:
    """Verify appended human labels and emit an exact-150 scoring sensitivity set."""

    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError("adjudicated scoring output must be absent or empty")
    scoring, by_system = load_qualification_scoring(scoring_dir, allowed_formats=(SCORING_FORMAT,))
    deterministic = _ordered_episodes(by_system)

    input_manifest_path = adjudication_input_dir / "manifest.json"
    input_manifest = _load_object(input_manifest_path)
    if input_manifest.get("format") != ADJUDICATION_INPUT_FORMAT:
        raise ValueError("unsupported qualification adjudication input")
    _verify_hash(input_manifest, "manifest_sha256", "qualification adjudication input")
    if (
        input_manifest.get("scoring_sha256") != scoring["scoring_sha256"]
        or input_manifest.get("source_plan_sha256") != scoring["source_plan_sha256"]
        or input_manifest.get("episode_count") != 150
    ):
        raise ValueError("qualification adjudication input/scoring mismatch")
    input_row = input_manifest.get("scored_episodes") or {}
    input_path = adjudication_input_dir / str(input_row.get("relative_path") or "")
    if not input_path.is_file() or _file_sha256(input_path) != input_row.get("sha256"):
        raise ValueError("qualification adjudication input artifact mismatch")
    input_episodes = list(read_episodes(input_path))
    if [item.model_dump(mode="json") for item in input_episodes] != [
        item.model_dump(mode="json") for item in deterministic
    ] or input_manifest.get("episode_content_sha256") != adjudication_episode_content_sha256(
        input_episodes
    ):
        raise ValueError("qualification adjudication input content drift")

    adjudication_manifest_path = adjudication_dir / "manifest.json"
    adjudication_manifest = _load_object(adjudication_manifest_path)
    if adjudication_manifest.get("format") != "mathaudit-adjudication-v0.1":
        raise ValueError("unsupported adjudication manifest")
    _verify_hash(adjudication_manifest, "manifest_sha256", "adjudication manifest")
    if (adjudication_manifest.get("input_hashes") or {}).get("episodes") != input_manifest[
        "episode_content_sha256"
    ]:
        raise ValueError("adjudication was not applied to the frozen input episodes")
    if (
        adjudication_manifest.get("guide_version") != guide_version
        or adjudication_manifest.get("guide_sha256") != guide_sha256
    ):
        raise ValueError("adjudication guide identity differs from the frozen guide")
    if adjudication_manifest.get("item_count", 0) < 150:
        raise ValueError("adjudication sensitivity requires at least 150 double-rated items")
    artifact_rows = adjudication_manifest.get("artifacts")
    if not isinstance(artifact_rows, list):
        raise ValueError("adjudication artifacts are missing")
    matches = [row for row in artifact_rows if row.get("path") == "episodes.jsonl"]
    if len(matches) != 1:
        raise ValueError("adjudicated episodes artifact registration mismatch")
    adjudicated_path = adjudication_dir / "episodes.jsonl"
    if not adjudicated_path.is_file() or _file_sha256(adjudicated_path) != matches[0].get("sha256"):
        raise ValueError("adjudicated episodes artifact hash mismatch")
    adjudicated = list(read_episodes(adjudicated_path))
    if len(adjudicated) != 150:
        raise ValueError("adjudicated episode set is not exact 150")
    adjudicated_by_id = {episode.episode_id: episode for episode in adjudicated}
    if len(adjudicated_by_id) != 150 or set(adjudicated_by_id) != {
        episode.episode_id for episode in deterministic
    }:
        raise ValueError("adjudicated episode identifiers differ from scoring input")
    for base in deterministic:
        updated = adjudicated_by_id[base.episode_id]
        if _without_labels(updated) != _without_labels(base):
            raise ValueError("adjudication changed non-label episode content")
        if updated.labels[: len(base.labels)] != base.labels:
            raise ValueError("adjudication changed deterministic labels")
        if any(
            label.scorer_type.value not in {"human", "adjudicated"}
            for label in updated.labels[len(base.labels) :]
        ):
            raise ValueError("adjudication appended an unsupported scorer type")

    output_dir.mkdir(parents=True, exist_ok=True)
    scored_dir = output_dir / "scored"
    artifacts = []
    label_counts: Counter[str] = Counter()
    for system_id in SYSTEM_IDS:
        episodes = [adjudicated_by_id[episode.episode_id] for episode in by_system[system_id]]
        for episode in episodes:
            for label in episode.labels:
                label_counts[label.value.value] += 1
        path = scored_dir / (system_id + ".jsonl")
        write_episodes(path, episodes)
        artifacts.append(
            {
                "system_id": system_id,
                "relative_path": path.relative_to(output_dir).as_posix(),
                "sha256": _file_sha256(path),
                "episodes": 50,
            }
        )
    manifest = {
        "format": ADJUDICATED_SCORING_FORMAT,
        "source_plan_sha256": scoring["source_plan_sha256"],
        "composite_sha256": scoring["composite_sha256"],
        "base_scoring_sha256": scoring["scoring_sha256"],
        "adjudication_input_sha256": input_manifest["manifest_sha256"],
        "adjudication_manifest_sha256": adjudication_manifest["manifest_sha256"],
        "adjudication_manifest_raw_sha256": _file_sha256(adjudication_manifest_path),
        "adjudication_guide_version": guide_version,
        "adjudication_guide_sha256": guide_sha256,
        "adjudication_item_count": adjudication_manifest["item_count"],
        "episode_count": 150,
        "system_episode_counts": {system_id: 50 for system_id in SYSTEM_IDS},
        "label_counts": dict(sorted(label_counts.items())),
        "scored_artifacts": artifacts,
        "correctness_labels_computed": True,
        "label_variant": "adjudicated",
        "deterministic_labels_preserved": True,
        "human_adjudication_applied": True,
        "contains_prompt_or_response_text": False,
    }
    manifest["scoring_sha256"] = sha256_json(manifest)
    (output_dir / "scoring-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def score_qualification_composite(*, composite_dir: Path, output_dir: Path) -> Dict[str, Any]:
    """Score only a self-hashed, exact-150 outcome-blind composite."""

    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError("qualification scoring output must be absent or empty")
    composite_path = composite_dir / "composite-manifest.json"
    composite = _load_object(composite_path)
    if composite.get("format") not in {
        "mathaudit-qualification-composite-v0.1",
        "mathaudit-qualification-composite-v0.2",
        "mathaudit-qualification-composite-v0.3",
    }:
        raise ValueError("unsupported qualification composite")
    _verify_hash(composite, "composite_sha256", "qualification composite")
    if composite.get("episode_count") != 150 or composite.get("system_episode_counts") != {
        "mathrouter": 50,
        "icma": 50,
        "mathgoal": 50,
    }:
        raise ValueError("qualification composite is not exact 150 / 50-per-system")
    if (
        composite.get("outcome_blind") is not True
        or composite.get("correctness_aggregates_computed") is not False
    ):
        raise ValueError("qualification composite crossed the scoring boundary early")
    rows = composite.get("canonical_artifacts")
    if not isinstance(rows, list):
        raise ValueError("qualification composite canonical artifacts are missing")
    by_system = {row.get("system_id"): row for row in rows if isinstance(row, dict)}
    if set(by_system) != set(SYSTEM_IDS):
        raise ValueError("qualification composite system set mismatch")

    output_dir.mkdir(parents=True, exist_ok=True)
    scored_dir = output_dir / "scored"
    artifacts = []
    label_counts: Counter[str] = Counter()
    episode_count = 0
    for system_id in SYSTEM_IDS:
        source_row = by_system[system_id]
        source_path = composite_dir / str(source_row["relative_path"])
        if (
            not source_path.is_file()
            or _file_sha256(source_path) != source_row["sha256"]
            or source_row.get("records") != 50
        ):
            raise ValueError("qualification composite canonical artifact mismatch")
        episodes = list(read_episodes(source_path))
        if len(episodes) != 50 or any(episode.labels for episode in episodes):
            raise ValueError("qualification canonical input is not an unscored 50-episode set")
        scored = [score_episode(episode) for episode in episodes]
        for episode in scored:
            for label in episode.labels:
                label_counts[label.value.value] += 1
        target = scored_dir / (system_id + ".jsonl")
        write_episodes(target, scored)
        artifacts.append(
            {
                "system_id": system_id,
                "relative_path": target.relative_to(output_dir).as_posix(),
                "sha256": _file_sha256(target),
                "episodes": len(scored),
            }
        )
        episode_count += len(scored)
    manifest = {
        "format": SCORING_FORMAT,
        "source_plan_sha256": composite["source_plan_sha256"],
        "composite_sha256": composite["composite_sha256"],
        "composite_manifest_raw_sha256": _file_sha256(composite_path),
        "scorer": {"name": SCORER_NAME, "version": SCORER_VERSION},
        "episode_count": episode_count,
        "system_episode_counts": {system_id: 50 for system_id in SYSTEM_IDS},
        "label_counts": dict(sorted(label_counts.items())),
        "scored_artifacts": artifacts,
        "correctness_labels_computed": True,
        "contains_prompt_or_response_text": False,
    }
    manifest["scoring_sha256"] = sha256_json(manifest)
    (output_dir / "scoring-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest
