# SPDX-License-Identifier: MIT

"""Preregistered analysis of a deterministically scored qualification composite."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from statistics import median
from typing import Any, Dict, List, Sequence, Tuple

from .hashing import sha256_json
from .metrics import (
    availability_profile,
    cofailure,
    conflict_adoption,
    cost_profile,
    effective_support_equicorrelated,
    final_outcome_profile,
    pairwise_dependence,
    resolved_source_labels,
    source_type_dependence,
    text_repetition_profile,
    transition_metrics,
)
from .models import Episode, LabelValue, SourceType
from .qualification_scoring import load_qualification_scoring

ANALYSIS_FORMAT = "mathaudit-qualification-analysis-v0.1"
CONFIG_FORMAT = "mathaudit-qualification-analysis-config-v0.1"
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


def _pair(value: Any, label: str, *, allow_equal: bool = False) -> Tuple[str, str]:
    if (
        not isinstance(value, list)
        or len(value) != 2
        or not all(isinstance(item, str) and item for item in value)
        or (not allow_equal and value[0] == value[1])
    ):
        qualifier = "two non-empty strings" if allow_equal else "two distinct non-empty strings"
        raise ValueError("%s must contain %s" % (label, qualifier))
    return value[0], value[1]


def _validate_config(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    required = {
        "format",
        "source_plan_sha256",
        "minimum_complete_cases",
        "bootstrap_replicates",
        "seed",
        "expected_panel_episode_count",
        "panels",
    }
    if set(config) != required or config.get("format") != CONFIG_FORMAT:
        raise ValueError("qualification analysis config fields/format are invalid")
    if config.get("expected_panel_episode_count") != 25:
        raise ValueError("qualification analysis panels must preregister 25 episodes")
    if (
        not isinstance(config.get("minimum_complete_cases"), int)
        or isinstance(config.get("minimum_complete_cases"), bool)
        or config["minimum_complete_cases"] < 1
    ):
        raise ValueError("minimum_complete_cases must be positive")
    if (
        not isinstance(config.get("bootstrap_replicates"), int)
        or isinstance(config.get("bootstrap_replicates"), bool)
        or config["bootstrap_replicates"] < 0
    ):
        raise ValueError("bootstrap_replicates cannot be negative")
    if not isinstance(config.get("seed"), int) or isinstance(config.get("seed"), bool):
        raise ValueError("seed must be an integer")
    panels = config.get("panels")
    if not isinstance(panels, list) or len(panels) != 6:
        raise ValueError("qualification analysis requires six system/stratum panels")
    seen = set()
    validated = []
    fields = {
        "panel_id",
        "system_id",
        "stratum",
        "exact_pairs",
        "source_type_pairs",
        "cofailure_source_sets",
        "transition_directions",
        "utilization_directions",
        "text_repetition_pairs",
    }
    for panel in panels:
        if not isinstance(panel, dict) or set(panel) != fields:
            raise ValueError("qualification analysis panel fields are invalid")
        panel_id = panel.get("panel_id")
        system_id = panel.get("system_id")
        stratum = panel.get("stratum")
        if (
            not isinstance(panel_id, str)
            or not panel_id
            or panel_id in seen
            or system_id not in SYSTEM_IDS
            or not isinstance(stratum, str)
            or not stratum
        ):
            raise ValueError("qualification analysis panel identity is invalid")
        seen.add(panel_id)
        normalized = dict(panel)
        for field in (
            "exact_pairs",
            "transition_directions",
            "utilization_directions",
            "text_repetition_pairs",
        ):
            values = panel[field]
            if not isinstance(values, list):
                raise ValueError("%s must be an array" % field)
            normalized[field] = [_pair(value, field) for value in values]
        type_pairs = panel["source_type_pairs"]
        if not isinstance(type_pairs, list):
            raise ValueError("source_type_pairs must be an array")
        normalized["source_type_pairs"] = [
            _pair(value, "source_type_pairs", allow_equal=True) for value in type_pairs
        ]
        type_values = []
        for source_a, source_b in normalized["source_type_pairs"]:
            try:
                type_values.append((SourceType(source_a), SourceType(source_b)))
            except ValueError as exc:
                raise ValueError("source_type_pairs contains an unknown type") from exc
        normalized["source_type_pairs"] = type_values
        sets = panel["cofailure_source_sets"]
        if not isinstance(sets, list):
            raise ValueError("cofailure_source_sets must be an array")
        normalized_sets = []
        for item in sets:
            if (
                not isinstance(item, dict)
                or set(item) != {"set_id", "source_ids"}
                or not isinstance(item["set_id"], str)
                or not item["set_id"]
                or not isinstance(item["source_ids"], list)
                or len(item["source_ids"]) < 2
                or len(set(item["source_ids"])) != len(item["source_ids"])
                or not all(isinstance(value, str) and value for value in item["source_ids"])
            ):
                raise ValueError("cofailure source set is invalid")
            normalized_sets.append(copy.deepcopy(item))
        normalized["cofailure_source_sets"] = normalized_sets
        validated.append(normalized)
    if {(item["system_id"], item["stratum"]) for item in validated} != {
        (system_id, stratum) for system_id in SYSTEM_IDS for stratum in ("standard", "hard_gt_5")
    }:
        raise ValueError("qualification panels must cover every system/stratum cell")
    return validated


def _load_scored(scoring_dir: Path) -> Tuple[Dict[str, Any], List[Episode]]:
    manifest, by_system = load_qualification_scoring(scoring_dir)
    return manifest, [episode for system_id in SYSTEM_IDS for episode in by_system[system_id]]


def _binary_type_counts(episodes: Sequence[Episode], source_type: SourceType) -> List[int]:
    values = []
    for episode in episodes:
        labels = resolved_source_labels(episode)
        types = {source.source_id: source.source_type for source in episode.sources}
        values.append(
            sum(
                types.get(source_id) == source_type
                and label in {LabelValue.correct, LabelValue.incorrect}
                for source_id, label in labels.items()
            )
        )
    return values


def _effective_support_summary(
    episodes: Sequence[Episode], dependence: Dict[str, Any]
) -> Dict[str, Any]:
    source_type = SourceType(dependence["source_type_a"])
    counts = _binary_type_counts(episodes, source_type)
    rho = dependence.get("phi_episode_balanced")
    maximum = max(counts) if counts else 0
    curve = []
    if rho is not None:
        for k in range(1, maximum + 1):
            try:
                value = effective_support_equicorrelated(k, float(rho))
            except ValueError:
                value = None
            curve.append({"k": k, "effective_support": value})
    return {
        "source_type": source_type.value,
        "binary_source_count": {
            "minimum": min(counts) if counts else None,
            "median": median(counts) if counts else None,
            "maximum": maximum if counts else None,
        },
        "rho_proxy": rho,
        "curve": curve,
        "model_based_not_literal_votes": True,
    }


def build_qualification_analysis(
    *, scoring_dir: Path, config_path: Path, output_path: Path
) -> Dict[str, Any]:
    """Build the preregistered six-panel audit without cross-panel ranking."""

    if output_path.exists():
        raise FileExistsError("qualification analysis output already exists")
    config = _load_object(config_path)
    panels = _validate_config(config)
    scoring, episodes = _load_scored(scoring_dir)
    if scoring.get("source_plan_sha256") != config["source_plan_sha256"]:
        raise ValueError("qualification analysis/source plan mismatch")
    minimum = config["minimum_complete_cases"]
    replicates = config["bootstrap_replicates"]
    seed = config["seed"]
    results = []
    for panel in panels:
        selected = [
            episode
            for episode in episodes
            if episode.system.system_id == panel["system_id"]
            and episode.problem.stratum == panel["stratum"]
        ]
        if len(selected) != config["expected_panel_episode_count"]:
            raise ValueError("qualification panel does not contain exactly 25 episodes")
        observed_sources = {source.source_id for episode in selected for source in episode.sources}
        exact_pairs = []
        for source_a, source_b in panel["exact_pairs"]:
            if source_a not in observed_sources or source_b not in observed_sources:
                raise ValueError("preregistered exact source is unobserved")
            item = pairwise_dependence(
                selected,
                source_a,
                source_b,
                bootstrap_replicates=replicates,
                seed=seed,
            )
            item["minimum_complete_cases"] = minimum
            item["precision_flag"] = (
                "adequate" if item["complete_cases"] >= minimum else "imprecise"
            )
            exact_pairs.append(item)
        type_pairs = []
        support = []
        for source_type_a, source_type_b in panel["source_type_pairs"]:
            for relation in ("all", "same", "different"):
                item = source_type_dependence(
                    selected,
                    source_type_a,
                    source_type_b,
                    bootstrap_replicates=replicates,
                    seed=seed,
                    provenance_relation=relation,
                )
                item["minimum_complete_cases"] = minimum
                item["precision_flag"] = (
                    "adequate" if item["episodes_with_pairs"] >= minimum else "imprecise"
                )
                type_pairs.append(item)
                if source_type_a == source_type_b and relation == "all":
                    support.append(_effective_support_summary(selected, item))
        results.append(
            {
                "panel_id": panel["panel_id"],
                "system_id": panel["system_id"],
                "stratum": panel["stratum"],
                "episode_count": len(selected),
                "source_inventory": sorted(observed_sources),
                "availability": [
                    availability_profile(selected, source_id)
                    for source_id in sorted(observed_sources)
                ],
                "cost": [
                    cost_profile(selected, source_id) for source_id in sorted(observed_sources)
                ],
                "exact_pairwise": exact_pairs,
                "source_type_pairwise": type_pairs,
                "cofailure": [
                    {
                        "set_id": item["set_id"],
                        "result": cofailure(selected, item["source_ids"]),
                    }
                    for item in panel["cofailure_source_sets"]
                ],
                "transitions": [
                    transition_metrics(selected, source_a, source_b)
                    for source_a, source_b in panel["transition_directions"]
                ],
                "utilization": [
                    conflict_adoption(selected, source_a, source_b)
                    for source_a, source_b in panel["utilization_directions"]
                ],
                "text_repetition": [
                    text_repetition_profile(selected, source_a, source_b)
                    for source_a, source_b in panel["text_repetition_pairs"]
                ],
                "effective_support": support,
                "final_outcomes": final_outcome_profile(selected),
            }
        )
    result = {
        "format": ANALYSIS_FORMAT,
        "source_plan_sha256": config["source_plan_sha256"],
        "scoring_sha256": scoring["scoring_sha256"],
        "label_variant": scoring.get("label_variant", "deterministic"),
        "config_raw_sha256": _file_sha256(config_path),
        "episode_count": len(episodes),
        "panels": results,
        "analysis_config": {
            "minimum_complete_cases": minimum,
            "bootstrap_replicates": replicates,
            "seed": seed,
            "unit_of_inference_for_type_pairs": "episode",
        },
        "system_ranking_computed": False,
        "interpretation_limits": [
            "Source-type phi is episode-balanced and cluster-bootstrapped; pair-weighted phi is sensitivity only.",
            "Phi bootstrap outputs expose requested, defined and undefined replicates; percentile ranges are conditional on defined phi draws and do not establish nominal coverage.",
            "Source-type pairs are split into all, same-provenance and different-provenance estimates.",
            "Effective support is an equicorrelation model summary, not a literal vote count.",
            "Repair, harm and utilization are descriptive because source invocation is selective.",
            "Exact text repetition is not semantic equivalence or correctness.",
            "No cross-panel pooling or system ranking is implicit.",
        ],
    }
    result["analysis_sha256"] = sha256_json(result)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result
