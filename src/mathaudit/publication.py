# SPDX-License-Identifier: MIT

"""Deterministic, preregistered publication tables, SVG figures, and manifests."""

from __future__ import annotations

import csv
import html
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

from . import __version__
from .hashing import sha256_json
from .metrics import (
    availability_profile,
    cofailure,
    conflict_adoption,
    cost_profile,
    final_outcome_profile,
    pairwise_dependence,
    transition_metrics,
)
from .models import Episode
from .sampling import file_sha256

_COLORS = ["#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00", "#56B4E9"]


def _validate_config(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    allowed_config = {
        "format",
        "minimum_complete_cases",
        "bootstrap_replicates",
        "seed",
        "panels",
    }
    if set(config) != allowed_config:
        raise ValueError("publication config fields must be exactly: %s" % sorted(allowed_config))
    if config.get("format") != "mathaudit-publication-config-v0.1":
        raise ValueError("publication config format must be mathaudit-publication-config-v0.1")
    panels = config.get("panels")
    if not isinstance(panels, list) or not panels:
        raise ValueError("publication config must contain at least one panel")
    seen = set()
    validated = []
    for panel in panels:
        if not isinstance(panel, dict):
            raise ValueError("each publication panel must be an object")
        required = {
            "panel_id",
            "system_id",
            "stratum",
            "source_ids",
            "cofailure_source_ids",
            "pair",
        }
        allowed_panel = required | {"transition_direction", "utilization_direction"}
        extra = sorted(set(panel).difference(allowed_panel))
        if extra:
            raise ValueError("publication panel has unsupported field(s): %s" % extra)
        missing = sorted(required.difference(panel))
        if missing:
            raise ValueError("publication panel is missing: %s" % missing)
        if not all(
            isinstance(panel[field], str) and panel[field]
            for field in ("panel_id", "system_id", "stratum")
        ):
            raise ValueError("panel_id, system_id, and stratum must be non-empty strings")
        panel_id = panel["panel_id"]
        if panel_id in seen:
            raise ValueError("publication panel IDs must be non-empty and unique")
        seen.add(panel_id)
        if not all(
            isinstance(panel[field], list)
            for field in ("source_ids", "cofailure_source_ids", "pair")
        ):
            raise ValueError("panel source_ids, cofailure_source_ids, and pair must be arrays")
        sources = panel["source_ids"]
        cofailure_sources = panel["cofailure_source_ids"]
        pair = panel["pair"]
        if not all(isinstance(value, str) for value in [*sources, *cofailure_sources, *pair]):
            raise ValueError("panel source IDs must be strings")
        if len(sources) < 2 or len(set(sources)) != len(sources) or not all(sources):
            raise ValueError("panel source_ids must contain at least two unique values")
        if len(pair) != 2 or pair[0] == pair[1] or not set(pair).issubset(sources):
            raise ValueError("panel pair must contain two distinct registered source_ids")
        if (
            len(cofailure_sources) < 2
            or len(set(cofailure_sources)) != len(cofailure_sources)
            or not set(cofailure_sources).issubset(sources)
        ):
            raise ValueError(
                "cofailure_source_ids must contain at least two unique registered source_ids"
            )
        normalized = dict(panel)
        normalized["panel_id"] = panel_id
        normalized["system_id"] = str(panel["system_id"])
        normalized["stratum"] = str(panel["stratum"])
        normalized["source_ids"] = sources
        normalized["cofailure_source_ids"] = cofailure_sources
        normalized["pair"] = pair
        for field in ("transition_direction", "utilization_direction"):
            direction = panel.get(field)
            if direction is not None:
                if not isinstance(direction, list) or not all(
                    isinstance(value, str) for value in direction
                ):
                    raise ValueError("%s must be an array of source IDs" % field)
                if (
                    len(direction) != 2
                    or direction[0] == direction[1]
                    or not set(direction).issubset(sources)
                ):
                    raise ValueError("%s must contain two registered source_ids" % field)
            normalized[field] = direction
        validated.append(normalized)
    return validated


def build_publication_data(episodes: Iterable[Episode], config: Dict[str, Any]) -> Dict[str, Any]:
    episodes = list(episodes)
    panels = _validate_config(config)
    minimum_value = config["minimum_complete_cases"]
    replicates_value = config["bootstrap_replicates"]
    seed_value = config["seed"]
    if isinstance(minimum_value, bool) or not isinstance(minimum_value, int) or minimum_value < 1:
        raise ValueError("minimum_complete_cases must be positive")
    if (
        isinstance(replicates_value, bool)
        or not isinstance(replicates_value, int)
        or replicates_value < 0
    ):
        raise ValueError("bootstrap_replicates cannot be negative")
    if isinstance(seed_value, bool) or not isinstance(seed_value, int):
        raise ValueError("seed must be an integer")
    minimum = minimum_value
    replicates = replicates_value
    seed = seed_value
    results = []
    for panel in panels:
        selected = [
            episode
            for episode in episodes
            if episode.system.system_id == panel["system_id"]
            and episode.problem.stratum == panel["stratum"]
        ]
        if not selected:
            raise ValueError("publication panel %s has no matching episodes" % panel["panel_id"])
        observed_sources = {source.source_id for episode in selected for source in episode.sources}
        missing_sources = sorted(set(panel["source_ids"]).difference(observed_sources))
        if missing_sources:
            raise ValueError(
                "publication panel %s has unobserved registered source(s): %s"
                % (panel["panel_id"], missing_sources)
            )
        pair = pairwise_dependence(
            selected,
            panel["pair"][0],
            panel["pair"][1],
            bootstrap_replicates=replicates,
            seed=seed,
        )
        pair["minimum_complete_cases"] = minimum
        pair["precision_flag"] = "adequate" if pair["complete_cases"] >= minimum else "imprecise"
        transition = panel["transition_direction"]
        utilization = panel["utilization_direction"]
        results.append(
            {
                "panel_id": panel["panel_id"],
                "system_id": panel["system_id"],
                "stratum": panel["stratum"],
                "episode_count": len(selected),
                "source_ids": panel["source_ids"],
                "cofailure_source_ids": panel["cofailure_source_ids"],
                "availability": [
                    availability_profile(selected, source_id) for source_id in panel["source_ids"]
                ],
                "pairwise": pair,
                "cofailure": cofailure(selected, panel["cofailure_source_ids"]),
                "transition": (
                    transition_metrics(selected, transition[0], transition[1])
                    if transition
                    else None
                ),
                "utilization": (
                    conflict_adoption(selected, utilization[0], utilization[1])
                    if utilization
                    else None
                ),
                "final_outcomes": final_outcome_profile(selected),
                "cost": [cost_profile(selected, source_id) for source_id in panel["source_ids"]],
            }
        )
    return {
        "format": "mathaudit-publication-data-v0.1",
        "tool_version": __version__,
        "panels": results,
        "analysis_config": {
            "minimum_complete_cases": minimum,
            "bootstrap_replicates": replicates,
            "seed": seed,
        },
        "interpretation_limits": [
            "Panels are exact system-by-stratum subsets; no cross-panel pooling is implicit.",
            "Phi uses jointly binary-scorable complete cases and is marked imprecise below the registered minimum.",
            "All-wrong beta is computed directly from the registered source set, not inferred from pairwise phi.",
            "Repair, harm, and utilization are descriptive; selective invocation prevents causal interpretation.",
        ],
    }


def _write_csv(path: Path, fieldnames: Sequence[str], rows: Sequence[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _flat_interval(item: Dict[str, Any], field: str, prefix: str) -> Dict[str, Any]:
    interval = item.get("intervals_exact_95", {}).get(field, [None, None])
    return {prefix + "_low": interval[0], prefix + "_high": interval[1]}


def _write_tables(root: Path, data: Dict[str, Any]) -> List[Path]:
    availability_rows = []
    pair_rows = []
    cofailure_rows = []
    transition_rows = []
    utilization_rows = []
    final_rows = []
    cost_rows = []
    for panel in data["panels"]:
        identity = {
            "panel_id": panel["panel_id"],
            "system_id": panel["system_id"],
            "stratum": panel["stratum"],
        }
        for item in panel["availability"]:
            registered = item["registered_episodes"]
            denominators = item["episode_denominators"]
            row = {
                **identity,
                "source_id": item["source_id"],
                "registered": registered,
                "eligible": denominators["eligible"],
                "called": denominators["called"],
                "produced": denominators["produced"],
                "binary_scorable": item["binary_scorable"],
                "correct": item["correct"],
                "eligible_over_registered": denominators["eligible"] / registered,
                "called_over_registered": denominators["called"] / registered,
                "produced_over_registered": denominators["produced"] / registered,
                "scorable_over_registered": item["binary_scorable"] / registered,
                "conditional_correctness": item["conditional_correctness"],
            }
            for field in (
                "eligible_over_registered",
                "called_over_registered",
                "produced_over_registered",
                "scorable_over_registered",
            ):
                interval = item["episode_proportions_exact_95"][field]
                row[field + "_low"] = interval[0]
                row[field + "_high"] = interval[1]
            row.update(_flat_interval(item, "conditional_correctness", "conditional_correctness"))
            availability_rows.append(row)
        pair = panel["pairwise"]
        pair_rows.append(
            {
                **identity,
                "source_a": pair["source_a"],
                "source_b": pair["source_b"],
                "complete_cases": pair["complete_cases"],
                **pair["cells"],
                "phi": pair["phi"],
                "phi_low": pair["phi_bootstrap_95"][0],
                "phi_high": pair["phi_bootstrap_95"][1],
                "joint_error_probability": pair["joint_error_probability"],
                "odds_ratio_haldane": pair["odds_ratio_haldane"],
                "mutual_information_nats": pair["mutual_information_nats"],
                "precision_flag": pair["precision_flag"],
            }
        )
        cofailure = panel["cofailure"]
        cofailure_rows.append(
            {
                **identity,
                "source_ids": "|".join(cofailure["source_ids"]),
                "registered": cofailure["registered_episodes"],
                "complete_cases": cofailure["complete_cases"],
                "complete_all_wrong": cofailure["complete_all_wrong"],
                "beta": cofailure["complete_case_beta"],
                "beta_low": cofailure["complete_case_beta_exact_95"][0],
                "beta_high": cofailure["complete_case_beta_exact_95"][1],
                "operational_no_correct_support": cofailure["operational_no_correct_support"],
                "operational_no_correct_support_rate": cofailure[
                    "operational_no_correct_support_rate"
                ],
            }
        )
        if panel["transition"]:
            item = panel["transition"]
            row = {**identity, "upstream": item["upstream"], "checker": item["checker"]}
            row.update(item["counts"])
            for field in (
                "repair_opportunity_rate",
                "repair_realization_rate",
                "harm_opportunity_rate",
                "harm_realization_rate",
            ):
                row[field] = item[field]
                row.update(_flat_interval(item, field, field))
            row["causal_interpretation"] = item["causal_interpretation"]
            transition_rows.append(row)
        if panel["utilization"]:
            item = panel["utilization"]
            row = {**identity, "upstream": item["upstream"], "checker": item["checker"]}
            row.update(item["counts"])
            for field in ("direct_checker_adoption_rate", "proxy_final_exact_match_rate"):
                row[field] = item[field]
                row.update(_flat_interval(item, field, field))
            row["causal_interpretation"] = item["causal_interpretation"]
            utilization_rows.append(row)
        final = panel["final_outcomes"]
        final_row = {
            **identity,
            **{key: value for key, value in final.items() if key != "intervals_exact_95"},
        }
        for field in ("survival_rate", "conditional_accuracy", "end_to_end_accuracy"):
            final_row.update(_flat_interval(final, field, field))
        final_rows.append(final_row)
        for source in panel["cost"]:
            for metric, distribution in source["metrics"].items():
                cost_rows.append(
                    {
                        **identity,
                        "source_id": source["source_id"],
                        "metric": metric,
                        **distribution,
                    }
                )

    tables = {
        "availability.csv": availability_rows,
        "pairwise.csv": pair_rows,
        "cofailure.csv": cofailure_rows,
        "transitions.csv": transition_rows,
        "utilization.csv": utilization_rows,
        "final_outcomes.csv": final_rows,
        "cost.csv": cost_rows,
    }
    paths = []
    for name, rows in tables.items():
        path = root / "tables" / name
        fields = list(rows[0]) if rows else ["panel_id"]
        for row in rows[1:]:
            for field in row:
                if field not in fields:
                    fields.append(field)
        _write_csv(path, fields, rows)
        paths.append(path)
    return paths


def _svg_document(title: str, description: str, width: int, height: int, body: str) -> str:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" role="img" '
        'aria-labelledby="title description" viewBox="0 0 %d %d">'
        '<title id="title">%s</title><desc id="description">%s</desc>'
        '<rect width="100%%" height="100%%" fill="white"/>'
        "<style>text{font-family:Arial,sans-serif;fill:#1f2937}.axis{stroke:#9ca3af;stroke-width:1}"
        ".grid{stroke:#e5e7eb;stroke-width:1}.label{font-size:12px}.small{font-size:10px;fill:#4b5563}"
        ".title{font-size:18px;font-weight:700}</style>%s</svg>"
        % (width, height, html.escape(title), html.escape(description), body)
    )


def _axis(left: int, right: int, y: int, *, low: float = 0.0, high: float = 1.0) -> str:
    parts = ['<line class="axis" x1="%d" y1="%d" x2="%d" y2="%d"/>' % (left, y, right, y)]
    for index in range(5):
        fraction = index / 4
        x = left + fraction * (right - left)
        value = low + fraction * (high - low)
        parts.append(
            '<line class="grid" x1="%.1f" y1="%d" x2="%.1f" y2="%d"/>' % (x, y - 5, x, y + 5)
        )
        parts.append(
            '<text class="small" x="%.1f" y="%d" text-anchor="middle">%.2g</text>'
            % (x, y + 18, value)
        )
    return "".join(parts)


def _availability_svg(data: Dict[str, Any]) -> str:
    rows = [(panel, item) for panel in data["panels"] for item in panel["availability"]]
    width, row_height = 1120, 34
    height = 100 + row_height * len(rows) + 45
    left, right = 300, 1060
    body = ['<text class="title" x="24" y="30">Availability before dependence</text>']
    body.append(_axis(left, right, 62))
    legend = [
        ("eligible", _COLORS[0]),
        ("called", _COLORS[1]),
        ("produced", _COLORS[2]),
        ("binary scorable", _COLORS[3]),
    ]
    for index, (label, color) in enumerate(legend):
        x = 310 + index * 175
        body.append(
            '<circle cx="%d" cy="92" r="5" fill="%s"/><text class="small" x="%d" y="96">%s</text>'
            % (x, color, x + 10, label)
        )
    for row_index, (panel, item) in enumerate(rows):
        y = 118 + row_index * row_height
        registered = item["registered_episodes"]
        counts = item["episode_denominators"]
        values = [counts["eligible"], counts["called"], counts["produced"], item["binary_scorable"]]
        interval_fields = [
            "eligible_over_registered",
            "called_over_registered",
            "produced_over_registered",
            "scorable_over_registered",
        ]
        label = "%s · %s" % (panel["panel_id"], item["source_id"])
        body.append('<text class="label" x="24" y="%d">%s</text>' % (y + 4, html.escape(label)))
        for point_index, count in enumerate(values):
            rate = count / registered if registered else 0.0
            x = left + rate * (right - left)
            point_y = y + point_index * 4 - 6
            interval = item["episode_proportions_exact_95"][interval_fields[point_index]]
            if interval[0] is not None and interval[1] is not None:
                low_x = left + float(interval[0]) * (right - left)
                high_x = left + float(interval[1]) * (right - left)
                body.append(
                    '<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" stroke="%s" stroke-width="2" opacity="0.55"/>'
                    % (low_x, point_y, high_x, point_y, _COLORS[point_index])
                )
            body.append(
                '<circle cx="%.1f" cy="%d" r="5" fill="%s"><title>%d/%d = %.3f</title></circle>'
                % (x, point_y, _COLORS[point_index], count, registered, rate)
            )
    return _svg_document(
        "Availability before dependence",
        "Eligible, called, produced, and binary-scorable episode proportions by preregistered panel and source.",
        width,
        height,
        "".join(body),
    )


def _point_interval(
    body: List[str],
    value: Any,
    interval: Sequence[Any],
    left: int,
    right: int,
    y: int,
    low: float,
    high: float,
    color: str,
) -> None:
    if value is None:
        body.append('<text class="small" x="%d" y="%d">NA</text>' % (left, y + 4))
        return

    def scale(item: Any) -> float:
        return left + (float(item) - low) / (high - low) * (right - left)

    if len(interval) == 2 and interval[0] is not None and interval[1] is not None:
        body.append(
            '<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" stroke="%s" stroke-width="3"/>'
            % (scale(interval[0]), y, scale(interval[1]), y, color)
        )
    body.append(
        '<circle cx="%.1f" cy="%d" r="6" fill="%s"><title>%.4f</title></circle>'
        % (scale(value), y, color, float(value))
    )


def _dependence_svg(data: Dict[str, Any]) -> str:
    width, row_height = 1180, 46
    height = 110 + row_height * len(data["panels"])
    phi_left, phi_right = 260, 700
    beta_left, beta_right = 830, 1130
    body = [
        '<text class="title" x="24" y="30">Error dependence and joint-failure tail</text>',
        '<text class="label" x="%d" y="52">phi (bootstrap 95%%)</text>' % phi_left,
        '<text class="label" x="%d" y="52">all-wrong beta (exact 95%%)</text>' % beta_left,
        _axis(phi_left, phi_right, 70, low=-1.0, high=1.0),
        _axis(beta_left, beta_right, 70),
    ]
    for index, panel in enumerate(data["panels"]):
        y = 105 + index * row_height
        pair = panel["pairwise"]
        beta = panel["cofailure"]
        suffix = " †" if pair["precision_flag"] == "imprecise" else ""
        body.append(
            '<text class="label" x="24" y="%d">%s%s</text>'
            % (y + 4, html.escape(panel["panel_id"]), suffix)
        )
        _point_interval(
            body,
            pair["phi"],
            pair["phi_bootstrap_95"],
            phi_left,
            phi_right,
            y,
            -1.0,
            1.0,
            _COLORS[0],
        )
        _point_interval(
            body,
            beta["complete_case_beta"],
            beta["complete_case_beta_exact_95"],
            beta_left,
            beta_right,
            y,
            0.0,
            1.0,
            _COLORS[1],
        )
    body.append(
        '<text class="small" x="24" y="%d">† complete cases below registered minimum; value retained and marked imprecise.</text>'
        % (height - 12)
    )
    return _svg_document(
        "Error dependence and joint-failure tail",
        "Pairwise phi and directly computed all-source all-wrong beta with uncertainty intervals.",
        width,
        height,
        "".join(body),
    )


def _transition_svg(data: Dict[str, Any]) -> str:
    panels = [panel for panel in data["panels"] if panel["transition"] or panel["utilization"]]
    width, row_height = 1120, 42
    height = 150 + row_height * max(1, len(panels))
    left, right = 300, 1060
    fields = [
        ("repair opportunity", "transition", "repair_opportunity_rate"),
        ("repair realization", "transition", "repair_realization_rate"),
        ("harm opportunity", "transition", "harm_opportunity_rate"),
        ("harm realization", "transition", "harm_realization_rate"),
        ("direct adoption", "utilization", "direct_checker_adoption_rate"),
        ("exact-match proxy", "utilization", "proxy_final_exact_match_rate"),
    ]
    body = [
        '<text class="title" x="24" y="30">Repair, harm, and utilization</text>',
        _axis(left, right, 62),
    ]
    for index, (label, _, _) in enumerate(fields):
        x = 310 + (index % 3) * 245
        legend_y = 91 + (index // 3) * 24
        body.append(
            '<circle cx="%d" cy="%d" r="5" fill="%s"/><text class="small" x="%d" y="%d">%s</text>'
            % (x, legend_y, _COLORS[index], x + 10, legend_y + 4, label)
        )
    if not panels:
        body.append(
            '<text class="label" x="24" y="136">No directed transition or utilization registered.</text>'
        )
    for row_index, panel in enumerate(panels):
        y = 140 + row_index * row_height
        body.append(
            '<text class="label" x="24" y="%d">%s</text>' % (y + 4, html.escape(panel["panel_id"]))
        )
        for point_index, (_, block, field) in enumerate(fields):
            item = panel[block]
            value = None if item is None else item[field]
            if value is None:
                continue
            x = left + float(value) * (right - left)
            body.append(
                '<circle cx="%.1f" cy="%d" r="5" fill="%s"><title>%s = %.4f</title></circle>'
                % (x, y + point_index * 4 - 6, _COLORS[point_index], field, float(value))
            )
    return _svg_document(
        "Repair, harm, and utilization",
        "Descriptive repair and harm rates plus direct checker adoption and a separately labelled exact-text proxy.",
        width,
        height,
        "".join(body),
    )


def _write_figures(root: Path, data: Dict[str, Any]) -> List[Path]:
    figures = {
        "availability.svg": _availability_svg(data),
        "dependence_cofailure.svg": _dependence_svg(data),
        "repair_harm_utilization.svg": _transition_svg(data),
    }
    paths = []
    for name, content in figures.items():
        path = root / "figures" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content + "\n", encoding="utf-8")
        paths.append(path)
    return paths


def write_publication_bundle(
    output_dir: Path, episodes: Iterable[Episode], config: Dict[str, Any]
) -> Dict[str, Any]:
    """Write deterministic tables/figures and hash every artifact."""

    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError("publication output directory must be absent or empty")
    episodes = list(episodes)
    data = build_publication_data(episodes, config)
    output_dir.mkdir(parents=True, exist_ok=True)
    data_path = output_dir / "publication_data.json"
    data_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    paths = [data_path, *_write_tables(output_dir, data), *_write_figures(output_dir, data)]
    episode_hash = sha256_json(
        [episode.model_dump(mode="json", exclude_none=False) for episode in episodes]
    )
    config_hash = sha256_json(config)
    command = "mathaudit publish --input CANONICAL_JSONL --config PUBLICATION_CONFIG --output-dir OUTPUT_DIR"
    sidecars = []
    for figure in [path for path in paths if path.suffix == ".svg"]:
        sidecar = figure.with_suffix(figure.suffix + ".manifest.json")
        sidecar.write_text(
            json.dumps(
                {
                    "format": "mathaudit-figure-manifest-v0.1",
                    "tool_version": __version__,
                    "input_episode_bundle_sha256": episode_hash,
                    "publication_config_sha256": config_hash,
                    "command": command,
                    "output_relative_path": figure.relative_to(output_dir).as_posix(),
                    "output_sha256": file_sha256(figure),
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        sidecars.append(sidecar)
    paths.extend(sidecars)
    manifest = {
        "format": "mathaudit-publication-manifest-v0.1",
        "tool_version": __version__,
        "input_episode_bundle_sha256": episode_hash,
        "publication_config_sha256": config_hash,
        "command": command,
        "artifacts": [
            {
                "relative_path": path.relative_to(output_dir).as_posix(),
                "sha256": file_sha256(path),
            }
            for path in sorted(paths, key=lambda item: item.relative_to(output_dir).as_posix())
        ],
    }
    manifest["manifest_sha256"] = sha256_json(manifest)
    (output_dir / "publication_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest
