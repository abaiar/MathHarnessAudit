# SPDX-License-Identifier: MIT

"""Blinded, double-rater mathematical outcome adjudication.

The workflow deliberately separates public rater material from the private
episode/source linkage.  Human labels are appended to canonical episodes; the
deterministic scoring path is never overwritten.
"""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .hashing import sha256_json, sha256_text
from .io import write_episodes
from .models import (
    AdjudicationStatus,
    Episode,
    LabelValue,
    OutcomeLabel,
    ScorerType,
)

FORMAT = "mathaudit-adjudication-v0.1"
LABELS = {item.value for item in LabelValue}
CONFIDENCE = {"high", "medium", "low"}
CONFIDENCE_VALUE = {"high": 1.0, "medium": 0.67, "low": 0.33}
REASONS = {
    "exact",
    "numeric_equivalent",
    "symbolic_equivalent",
    "set_or_interval_equivalent",
    "multi_part_complete",
    "proof_valid",
    "missing_component",
    "domain_violation",
    "reference_ambiguous",
    "insufficient_context",
    "other",
}

DISPLAY_FIELDS = [
    "adjudication_id",
    "problem_sha256",
    "target_content_sha256",
    "reference_sha256",
    "problem_statement",
    "answer_to_judge",
    "answer_type",
    "reference_answer",
]
RATER_FIELDS = DISPLAY_FIELDS + [
    "annotator_id",
    "label",
    "confidence",
    "reason_code",
    "rationale",
    "timestamp_utc",
]
THIRD_FIELDS = DISPLAY_FIELDS + [
    "rater_a_label",
    "rater_a_reason_code",
    "rater_a_rationale",
    "rater_b_label",
    "rater_b_reason_code",
    "rater_b_rationale",
    "third_annotator_id",
    "final_label",
    "confidence",
    "reason_code",
    "rationale",
    "timestamp_utc",
    "final_resolution",
]


def adjudication_episode_content_sha256(episodes: Sequence[Episode]) -> str:
    """Hash the ordered canonical episode content independently of file paths."""

    return sha256_json([episode.model_dump(mode="json") for episode in episodes])


def _ensure_empty_directory(path: Path) -> None:
    if path.exists() and any(path.iterdir()):
        raise FileExistsError("output directory must be absent or empty: %s" % path)
    path.mkdir(parents=True, exist_ok=True)


def _write_csv(path: Path, rows: Sequence[Dict[str, Any]], fields: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _read_csv(path: Path, fields: Sequence[str]) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = [field for field in fields if field not in (reader.fieldnames or [])]
        if missing:
            raise ValueError("%s is missing columns: %s" % (path, ", ".join(missing)))
        return [{key: str(value or "").strip() for key, value in row.items()} for row in reader]


def _artifact(path: Path, root: Path) -> Dict[str, str]:
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": sha256_text(path.read_text(encoding="utf-8-sig")),
    }


def _label_by_target(episode: Episode) -> Dict[str, OutcomeLabel]:
    priority = {
        ScorerType.adjudicated: 8,
        ScorerType.human: 7,
        ScorerType.formal: 6,
        ScorerType.executable: 5,
        ScorerType.symbolic: 4,
        ScorerType.numeric: 3,
        ScorerType.exact: 2,
        ScorerType.llm: 1,
    }
    result: Dict[str, OutcomeLabel] = {}
    for label in episode.labels:
        if label.target_type != "evidence":
            continue
        incumbent = result.get(label.target_id)
        if incumbent is None or (priority[label.scorer_type], label.created_at) > (
            priority[incumbent.scorer_type],
            incumbent.created_at,
        ):
            result[label.target_id] = label
    return result


def _source_for_evidence(episode: Episode, evidence_id: str) -> Optional[str]:
    observations = {item.observation_id: item.source_id for item in episode.source_observations}
    for item in episode.evidence:
        if item.evidence_id == evidence_id:
            return observations.get(item.observation_id)
    return None


def _target_rows(episodes: Iterable[Episode], key: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for episode in episodes:
        evidence = {item.evidence_id: item for item in episode.evidence}
        for target_id, proposal in _label_by_target(episode).items():
            item = evidence.get(target_id)
            if item is None:
                continue
            answer = item.content.text or item.content.normalized_answer or ""
            statement = episode.problem.statement or ""
            reference = episode.audit_only.gold or ""
            identity = "%s\x1f%s" % (episode.episode_id, target_id)
            adjudication_id = "adj_" + sha256_text(key + "\x1f" + identity)[:24]
            rows.append(
                {
                    "adjudication_id": adjudication_id,
                    "problem_sha256": sha256_text(statement),
                    "target_content_sha256": item.content.content_hash.value,
                    "reference_sha256": sha256_text(reference),
                    "display_answer_sha256": sha256_text(answer),
                    "answer_type_sha256": sha256_text(episode.problem.answer_type or ""),
                    "problem_statement": statement,
                    "answer_to_judge": answer,
                    "answer_type": episode.problem.answer_type or "",
                    "reference_answer": reference,
                    "episode_id": episode.episode_id,
                    "target_id": target_id,
                    "problem_id": episode.problem.problem_id,
                    "system_id": episode.system.system_id,
                    "source_id": _source_for_evidence(episode, target_id),
                    "stratum": episode.problem.stratum,
                    "gold_version": episode.problem.dataset_version or "unspecified",
                    "proposed_label": proposal.value.value,
                    "proposed_scorer_type": proposal.scorer_type.value,
                    "proposed_rule_id": proposal.rule_id,
                    "selection_rank": sha256_text(key + "\x1fselect\x1f" + identity),
                }
            )
    ids = [row["adjudication_id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("adjudication identifier collision")
    return rows


def _select_rows(rows: Sequence[Dict[str, Any]], audit_sample_size: int) -> List[Dict[str, Any]]:
    unresolved = [row for row in rows if row["proposed_label"] == LabelValue.unscorable.value]
    candidates = [row for row in rows if row["proposed_label"] != LabelValue.unscorable.value]
    groups: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = defaultdict(list)
    for row in candidates:
        groups[(row["system_id"], row["stratum"], row["proposed_label"])].append(row)
    for group in groups.values():
        group.sort(key=lambda item: item["selection_rank"])
    sampled: List[Dict[str, Any]] = []
    keys = sorted(groups)
    while len(sampled) < audit_sample_size and any(groups.values()):
        for group_key in keys:
            if groups[group_key] and len(sampled) < audit_sample_size:
                sampled.append(groups[group_key].pop(0))
    selected = unresolved + sampled
    return sorted(selected, key=lambda item: item["adjudication_id"])


def _validate_guide_identity(guide_version: str, guide_sha256: str) -> None:
    if not guide_version.strip():
        raise ValueError("guide_version must not be empty")
    if len(guide_sha256) != 64 or any(character not in "0123456789abcdef" for character in guide_sha256):
        raise ValueError("guide_sha256 must be a lowercase SHA-256 digest")


def export_adjudication_bundle(
    output_dir: Path,
    episodes: Iterable[Episode],
    *,
    blinding_key: str,
    guide_sha256: str,
    audit_sample_size: int = 50,
    minimum_item_count: int = 1,
    guide_version: str = "1.0",
    order_seed: int = 20260823,
) -> Dict[str, Any]:
    """Write private linkage plus two independently ordered blinded templates."""

    if not blinding_key.strip():
        raise ValueError("blinding key must not be empty")
    _validate_guide_identity(guide_version, guide_sha256)
    if audit_sample_size < 0:
        raise ValueError("audit_sample_size must be non-negative")
    if minimum_item_count < 1:
        raise ValueError("minimum_item_count must be positive")
    _ensure_empty_directory(output_dir)
    rows = _select_rows(_target_rows(list(episodes), blinding_key), audit_sample_size)
    if not rows:
        raise ValueError("no labelled evidence targets available for adjudication")
    if len(rows) < minimum_item_count:
        raise ValueError(
            "adjudication selection has %d items; minimum_item_count is %d"
            % (len(rows), minimum_item_count)
        )

    public_rows = [{field: row[field] for field in DISPLAY_FIELDS} for row in rows]
    for row in public_rows:
        row.update({field: "" for field in RATER_FIELDS if field not in DISPLAY_FIELDS})
    rater_a = sorted(
        public_rows,
        key=lambda item: sha256_text("%s:a:%s" % (order_seed, item["adjudication_id"])),
    )
    rater_b = sorted(
        public_rows,
        key=lambda item: sha256_text("%s:b:%s" % (order_seed, item["adjudication_id"])),
    )
    a_path = output_dir / "public" / "rater_a.csv"
    b_path = output_dir / "public" / "rater_b.csv"
    _write_csv(a_path, rater_a, RATER_FIELDS)
    _write_csv(b_path, rater_b, RATER_FIELDS)

    linkage = {
        "format": FORMAT,
        "guide_version": guide_version,
        "guide_sha256": guide_sha256,
        "selection": {
            "all_unscorable": True,
            "audit_sample_size_requested": audit_sample_size,
            "minimum_item_count": minimum_item_count,
            "order_seed": order_seed,
        },
        "blinding_key_sha256": sha256_text(blinding_key),
        "items": [
            {key: value for key, value in row.items() if key not in DISPLAY_FIELDS[4:]}
            for row in rows
        ],
    }
    linkage["linkage_sha256"] = sha256_json(linkage)
    linkage_path = output_dir / "private" / "linkage.json"
    linkage_path.parent.mkdir(parents=True, exist_ok=True)
    linkage_path.write_text(
        json.dumps(linkage, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    counts = Counter(row["proposed_label"] for row in rows)
    manifest = {
        "format": FORMAT,
        "guide_version": guide_version,
        "guide_sha256": guide_sha256,
        "item_count": len(rows),
        "selection_counts_private": dict(sorted(counts.items())),
        "linkage_sha256": linkage["linkage_sha256"],
        "artifacts": [_artifact(path, output_dir) for path in (a_path, b_path, linkage_path)],
    }
    manifest["manifest_sha256"] = sha256_json(manifest)
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def _parse_time(value: str, path: Path, item_id: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("%s: invalid timestamp for %s" % (path, item_id)) from exc
    if parsed.tzinfo is None:
        raise ValueError("%s: timestamp must include a timezone for %s" % (path, item_id))
    return parsed


def _validated_ratings(path: Path) -> Dict[str, Dict[str, str]]:
    rows = _read_csv(path, RATER_FIELDS)
    result: Dict[str, Dict[str, str]] = {}
    annotators = set()
    for row in rows:
        item_id = row["adjudication_id"]
        if not item_id or item_id in result:
            raise ValueError("%s: empty or duplicate adjudication_id" % path)
        if row["label"] not in LABELS:
            raise ValueError("%s: invalid label for %s" % (path, item_id))
        if row["confidence"] not in CONFIDENCE:
            raise ValueError("%s: invalid confidence for %s" % (path, item_id))
        if row["reason_code"] not in REASONS:
            raise ValueError("%s: invalid reason code for %s" % (path, item_id))
        if not row["annotator_id"] or not row["rationale"]:
            raise ValueError("%s: annotator and rationale are required for %s" % (path, item_id))
        _parse_time(row["timestamp_utc"], path, item_id)
        annotators.add(row["annotator_id"])
        result[item_id] = row
    if len(annotators) != 1:
        raise ValueError("%s must contain exactly one annotator pseudonym" % path)
    return result


def _check_rater_pair(
    a: Dict[str, Dict[str, str]], b: Dict[str, Dict[str, str]]
) -> Tuple[str, str]:
    if set(a) != set(b):
        raise ValueError("rater files must contain the same adjudication IDs")
    annotator_a = next(iter(a.values()))["annotator_id"]
    annotator_b = next(iter(b.values()))["annotator_id"]
    if annotator_a == annotator_b:
        raise ValueError("the two rater pseudonyms must differ")
    for item_id in a:
        for field in DISPLAY_FIELDS:
            if a[item_id][field] != b[item_id][field]:
                raise ValueError("rater display material differs for %s (%s)" % (item_id, field))
    return annotator_a, annotator_b


def _cohen_kappa(a: Sequence[str], b: Sequence[str]) -> Optional[float]:
    if not a:
        return None
    observed = sum(left == right for left, right in zip(a, b, strict=True)) / len(a)
    expected = sum(
        (a.count(label) / len(a)) * (b.count(label) / len(b)) for label in sorted(LABELS)
    )
    if expected == 1.0:
        return 1.0 if observed == 1.0 else None
    return (observed - expected) / (1.0 - expected)


def agreement_and_conflicts(
    output_dir: Path, rater_a_path: Path, rater_b_path: Path
) -> Dict[str, Any]:
    """Compute pre-discussion agreement and write a blinded third-pass queue."""

    _ensure_empty_directory(output_dir)
    a = _validated_ratings(rater_a_path)
    b = _validated_ratings(rater_b_path)
    annotator_a, annotator_b = _check_rater_pair(a, b)
    ids = sorted(a)
    labels_a = [a[item_id]["label"] for item_id in ids]
    labels_b = [b[item_id]["label"] for item_id in ids]
    agreements = sum(left == right for left, right in zip(labels_a, labels_b, strict=True))
    confusion = Counter(
        "%s|%s" % (left, right) for left, right in zip(labels_a, labels_b, strict=True)
    )
    report = {
        "format": FORMAT,
        "item_count": len(ids),
        "annotators": [annotator_a, annotator_b],
        "agreement_count": agreements,
        "disagreement_count": len(ids) - agreements,
        "raw_agreement": agreements / len(ids) if ids else None,
        "cohen_kappa": _cohen_kappa(labels_a, labels_b),
        "confusion": dict(sorted(confusion.items())),
        "qualification_targets": {"raw_agreement": 0.90, "cohen_kappa": 0.80},
    }
    report["targets_met"] = bool(
        report["raw_agreement"] is not None
        and report["raw_agreement"] >= 0.90
        and report["cohen_kappa"] is not None
        and report["cohen_kappa"] >= 0.80
    )
    report["report_sha256"] = sha256_json(report)
    report_path = output_dir / "agreement.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    conflicts: List[Dict[str, Any]] = []
    for item_id in ids:
        if a[item_id]["label"] == b[item_id]["label"]:
            continue
        row = {field: a[item_id][field] for field in DISPLAY_FIELDS}
        row.update(
            {
                "rater_a_label": a[item_id]["label"],
                "rater_a_reason_code": a[item_id]["reason_code"],
                "rater_a_rationale": a[item_id]["rationale"],
                "rater_b_label": b[item_id]["label"],
                "rater_b_reason_code": b[item_id]["reason_code"],
                "rater_b_rationale": b[item_id]["rationale"],
            }
        )
        row.update({field: "" for field in THIRD_FIELDS if field not in row})
        conflicts.append(row)
    conflicts_path = output_dir / "third_pass.csv"
    _write_csv(conflicts_path, conflicts, THIRD_FIELDS)
    return report


def _read_linkage(path: Path) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    claimed = payload.pop("linkage_sha256", None)
    if payload.get("format") != FORMAT or claimed != sha256_json(payload):
        raise ValueError("invalid linkage format or self-hash")
    items = payload.get("items")
    if not isinstance(items, list):
        raise ValueError("linkage items must be a list")
    result = {str(item["adjudication_id"]): item for item in items}
    if len(result) != len(items):
        raise ValueError("duplicate adjudication IDs in linkage")
    guide_version = payload.get("guide_version")
    guide_sha256 = payload.get("guide_sha256")
    if not isinstance(guide_version, str) or not isinstance(guide_sha256, str):
        raise ValueError("linkage is missing the guide identity")
    _validate_guide_identity(guide_version, guide_sha256)
    return result, {"guide_version": guide_version, "guide_sha256": guide_sha256}


def _validated_third(path: Optional[Path]) -> Dict[str, Dict[str, str]]:
    if path is None:
        return {}
    rows = _read_csv(path, THIRD_FIELDS)
    result = {}
    annotators = set()
    for row in rows:
        item_id = row["adjudication_id"]
        if not row["third_annotator_id"] or row["final_label"] not in LABELS:
            raise ValueError("%s: incomplete third-pass decision for %s" % (path, item_id))
        if row["confidence"] not in CONFIDENCE or row["reason_code"] not in REASONS:
            raise ValueError("%s: invalid third-pass confidence/reason for %s" % (path, item_id))
        if row["final_resolution"] not in {"resolved", "unresolved"} or not row["rationale"]:
            raise ValueError("%s: invalid third-pass resolution for %s" % (path, item_id))
        _parse_time(row["timestamp_utc"], path, item_id)
        if item_id in result:
            raise ValueError("%s: duplicate third-pass ID %s" % (path, item_id))
        annotators.add(row["third_annotator_id"])
        result[item_id] = row
    if len(annotators) > 1:
        raise ValueError("third-pass file must contain one adjudicator pseudonym")
    return result


def _human_label(
    item_id: str,
    linkage: Dict[str, Any],
    rating: Dict[str, str],
    *,
    rater_slot: str,
    guide_version: str,
    guide_sha256: str,
) -> OutcomeLabel:
    return OutcomeLabel(
        label_id="label:human:%s:%s" % (rater_slot, item_id),
        target_type="evidence",
        target_id=linkage["target_id"],
        value=LabelValue(rating["label"]),
        scorer_type=ScorerType.human,
        scorer_name="blinded_human_adjudicator",
        scorer_version=guide_version,
        rule_id="human_first_pass_v1",
        decision_path=["blinded", "independent", "first_pass", rater_slot],
        confidence=CONFIDENCE_VALUE[rating["confidence"]],
        adjudication_status=AdjudicationStatus.pending,
        annotator_id=rating["annotator_id"],
        created_at=_parse_time(rating["timestamp_utc"], Path("rating"), item_id),
        metadata={
            "adjudication_id": item_id,
            "confidence_category": rating["confidence"],
            "reason_code": rating["reason_code"],
            "rationale_sha256": sha256_text(rating["rationale"]),
            "gold_version": linkage["gold_version"],
            "guide_sha256": guide_sha256,
        },
    )


def apply_adjudication(
    output_dir: Path,
    episodes: Iterable[Episode],
    linkage_path: Path,
    rater_a_path: Path,
    rater_b_path: Path,
    *,
    third_pass_path: Optional[Path] = None,
    guide_version: str = "1.0",
    guide_sha256: str,
) -> Dict[str, Any]:
    """Append frozen first-pass and consensus labels and emit a hash manifest."""

    _ensure_empty_directory(output_dir)
    source_episodes = list(episodes)
    input_episode_content_sha256 = adjudication_episode_content_sha256(source_episodes)
    episode_list = [episode.model_copy(deep=True) for episode in source_episodes]
    _validate_guide_identity(guide_version, guide_sha256)
    linkage, linkage_guide = _read_linkage(linkage_path)
    if linkage_guide != {"guide_version": guide_version, "guide_sha256": guide_sha256}:
        raise ValueError("guide identity differs from the adjudication export")
    a = _validated_ratings(rater_a_path)
    b = _validated_ratings(rater_b_path)
    annotator_a, annotator_b = _check_rater_pair(a, b)
    if set(a) != set(linkage):
        raise ValueError("rater IDs and private linkage IDs differ")
    third = _validated_third(third_pass_path)
    disagreements = {item_id for item_id in a if a[item_id]["label"] != b[item_id]["label"]}
    if set(third) != disagreements:
        raise ValueError("third-pass IDs must exactly equal first-pass disagreements")
    third_annotators = {row["third_annotator_id"] for row in third.values()}
    if third_annotators.intersection({annotator_a, annotator_b}):
        raise ValueError("third-pass adjudicator must differ from both first-pass raters")
    for item_id, row in third.items():
        if any(row[field] != a[item_id][field] for field in DISPLAY_FIELDS):
            raise ValueError("third-pass display material changed for %s" % item_id)

    episodes_by_id = {episode.episode_id: episode for episode in episode_list}
    frozen: List[Dict[str, Any]] = []
    final_counts: Counter[str] = Counter()
    for item_id in sorted(linkage):
        link = linkage[item_id]
        episode = episodes_by_id.get(link["episode_id"])
        if episode is None:
            raise ValueError("linked episode is absent: %s" % link["episode_id"])
        evidence = next((item for item in episode.evidence if item.evidence_id == link["target_id"]), None)
        if evidence is None:
            raise ValueError("linked evidence is absent: %s" % link["target_id"])
        statement = episode.problem.statement or ""
        reference = episode.audit_only.gold or ""
        if (
            sha256_text(statement) != link["problem_sha256"]
            or evidence.content.content_hash.value != link["target_content_sha256"]
            or sha256_text(reference) != link["reference_sha256"]
        ):
            raise ValueError("episode content changed after adjudication export: %s" % item_id)
        for rating in (a[item_id], b[item_id]):
            if (
                sha256_text(rating["problem_statement"]) != link["problem_sha256"]
                or sha256_text(rating["answer_to_judge"])
                != link["display_answer_sha256"]
                or sha256_text(rating["answer_type"]) != link["answer_type_sha256"]
                or sha256_text(rating["reference_answer"]) != link["reference_sha256"]
            ):
                raise ValueError("rater display material changed for %s" % item_id)
        new_ids = {
            "label:human:a:%s" % item_id,
            "label:human:b:%s" % item_id,
            "label:adjudicated:%s" % item_id,
        }
        if new_ids.intersection(label.label_id for label in episode.labels):
            raise ValueError("adjudication labels already exist for %s" % item_id)
        human_a = _human_label(
            item_id,
            link,
            a[item_id],
            rater_slot="a",
            guide_version=guide_version,
            guide_sha256=guide_sha256,
        )
        human_b = _human_label(
            item_id,
            link,
            b[item_id],
            rater_slot="b",
            guide_version=guide_version,
            guide_sha256=guide_sha256,
        )
        episode.labels.extend([human_a, human_b])

        if item_id in disagreements:
            decision = third[item_id]
            final_value = decision["final_label"]
            resolution = decision["final_resolution"]
            if resolution == "unresolved":
                final_value = LabelValue.unscorable.value
            final_time = _parse_time(decision["timestamp_utc"], Path("third_pass"), item_id)
            confidence = CONFIDENCE_VALUE[decision["confidence"]]
            reason = decision["reason_code"]
            rationale_hash = sha256_text(decision["rationale"])
            adjudicator_id = decision["third_annotator_id"]
            path = ["blinded", "independent_double_rating", "third_pass", resolution]
        else:
            final_value = a[item_id]["label"]
            resolution = "unresolved" if final_value == LabelValue.unscorable.value else "resolved"
            final_time = max(human_a.created_at, human_b.created_at)
            confidence = min(human_a.confidence or 0.0, human_b.confidence or 0.0)
            reason = a[item_id]["reason_code"]
            rationale_hash = sha256_json(
                [sha256_text(a[item_id]["rationale"]), sha256_text(b[item_id]["rationale"])]
            )
            adjudicator_id = None
            path = ["blinded", "independent_double_rating", "agreement", resolution]
        status = (
            AdjudicationStatus.resolved
            if resolution == "resolved"
            else AdjudicationStatus.unresolved
        )
        final = OutcomeLabel(
            label_id="label:adjudicated:%s" % item_id,
            target_type="evidence",
            target_id=link["target_id"],
            value=LabelValue(final_value),
            scorer_type=ScorerType.adjudicated,
            scorer_name="blinded_double_review",
            scorer_version=guide_version,
            rule_id="double_review_with_third_pass_v1",
            decision_path=path,
            confidence=confidence,
            adjudication_status=status,
            annotator_id=adjudicator_id,
            created_at=final_time,
            metadata={
                "adjudication_id": item_id,
                "first_pass_annotators": [a[item_id]["annotator_id"], b[item_id]["annotator_id"]],
                "reason_code": reason,
                "rationale_sha256": rationale_hash,
                "gold_version": link["gold_version"],
                "guide_version": guide_version,
                "guide_sha256": guide_sha256,
            },
        )
        episode.labels.append(final)
        final_counts[final.value.value] += 1
        frozen.append(
            {
                "adjudication_id": item_id,
                "episode_id": link["episode_id"],
                "target_id": link["target_id"],
                "rater_a_label": a[item_id]["label"],
                "rater_b_label": b[item_id]["label"],
                "final_label": final.value.value,
                "adjudication_status": final.adjudication_status.value,
                "final_label_id": final.label_id,
            }
        )

    episodes_path = output_dir / "episodes.jsonl"
    write_episodes(episodes_path, episode_list)
    log_path = output_dir / "adjudication_log.jsonl"
    with log_path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in frozen:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    manifest = {
        "format": FORMAT,
        "guide_version": guide_version,
        "guide_sha256": guide_sha256,
        "item_count": len(frozen),
        "final_counts": dict(sorted(final_counts.items())),
        "unresolved_count": sum(
            row["adjudication_status"] == "unresolved" for row in frozen
        ),
        "input_hashes": {
            "episodes": input_episode_content_sha256,
            "linkage": sha256_text(linkage_path.read_text(encoding="utf-8")),
            "rater_a": sha256_text(rater_a_path.read_text(encoding="utf-8-sig")),
            "rater_b": sha256_text(rater_b_path.read_text(encoding="utf-8-sig")),
            "third_pass": (
                sha256_text(third_pass_path.read_text(encoding="utf-8-sig"))
                if third_pass_path
                else None
            ),
        },
        "artifacts": [_artifact(path, output_dir) for path in (episodes_path, log_path)],
    }
    manifest["manifest_sha256"] = sha256_json(manifest)
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest
