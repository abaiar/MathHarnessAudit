# SPDX-License-Identifier: MIT

"""Publication tables and SVGs derived only from frozen qualification analyses."""

from __future__ import annotations

import copy
import csv
import html
import json
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Sequence

from . import __version__
from .hashing import sha256_json
from .sampling import file_sha256

ANALYSIS_FORMAT = "mathaudit-qualification-analysis-v0.1"
DATA_FORMAT = "mathaudit-qualification-publication-data-v0.1"
MANIFEST_FORMAT = "mathaudit-qualification-publication-manifest-v0.1"

_NONPUBLIC_ANALYSIS_KEYS = {
    "answer",
    "api_key",
    "content",
    "credential",
    "gold",
    "normalized_answer",
    "prompt",
    "question",
    "rationale",
    "reference_answer",
    "request_id",
    "response",
    "statement",
    "text",
}
_SAFE_AGGREGATE_TEXT_PREFIX_KEYS = {"prompt_tokens", "response_tokens"}
_SECRET_SHAPE = re.compile(r"(?:^|[^A-Za-z0-9])sk-[A-Za-z0-9_-]{12,}")
_WINDOWS_ABSOLUTE_PATH = re.compile(r"^[A-Za-z]:[\\/]")
_UNC_ABSOLUTE_PATH = re.compile(r"^\\\\[^\\]+\\[^\\]+")
_POSIX_LOCAL_PATH = re.compile(r"^/(?:home|Users|root|tmp|var|mnt|workspace)(?:/|$)")
_EXPECTED_PUBLICATION_ARTIFACTS = {
    "publication-data.json",
    *(
        "tables/%s.csv" % name
        for name in (
            "availability",
            "cost",
            "exact_pairwise",
            "source_type_pairwise",
            "cofailure",
            "transitions",
            "utilization",
            "text_repetition",
            "effective_support",
            "final_outcomes",
        )
    ),
    *(
        "figures/%s.svg" % name
        for name in (
            "availability",
            "dependence",
            "repair_harm",
            "repetition",
        )
    ),
    *(
        "figures/%s.svg.manifest.json" % name
        for name in (
            "availability",
            "dependence",
            "repair_harm",
            "repetition",
        )
    ),
}


def _load_object(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("JSON document must be an object: %s" % path)
    return payload


def _verify_analysis(path: Path) -> Dict[str, Any]:
    payload = _load_object(path)
    claimed = payload.get("analysis_sha256")
    candidate = copy.deepcopy(payload)
    candidate.pop("analysis_sha256", None)
    if claimed != sha256_json(candidate):
        raise ValueError("qualification analysis self-hash mismatch")
    if (
        payload.get("format") != ANALYSIS_FORMAT
        or payload.get("episode_count") != 150
        or payload.get("label_variant") not in {"deterministic", "adjudicated"}
        or payload.get("system_ranking_computed") is not False
    ):
        raise ValueError("qualification analysis identity or claim boundary is invalid")
    panels = payload.get("panels")
    if not isinstance(panels, list) or len(panels) != 6:
        raise ValueError("qualification publication requires six panels")
    identities = {(item.get("system_id"), item.get("stratum")) for item in panels}
    if identities != {
        (system_id, stratum)
        for system_id in ("mathrouter", "icma", "mathgoal")
        for stratum in ("standard", "hard_gt_5")
    } or any(item.get("episode_count") != 25 for item in panels):
        raise ValueError("qualification publication panel coverage is invalid")
    for panel in panels:
        for field in (
            "availability",
            "cost",
            "exact_pairwise",
            "source_type_pairwise",
            "cofailure",
            "transitions",
            "utilization",
            "text_repetition",
            "effective_support",
            "final_outcomes",
        ):
            if field not in panel:
                raise ValueError("qualification analysis lacks publication field: %s" % field)
    return payload


def _walk_json(value: Any, path: str = "$") -> List[tuple[str, str, Any]]:
    rows: List[tuple[str, str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = "%s.%s" % (path, key)
            rows.append((child_path, str(key), child))
            rows.extend(_walk_json(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            rows.extend(_walk_json(child, "%s[%d]" % (path, index)))
    return rows


def verify_public_analysis_release(
    analysis_path: Path, *, config_path: Path | None = None
) -> Dict[str, Any]:
    """Verify that a frozen analysis is self-hashed and safe for aggregate release.

    This is an allow-boundary check, not a claim that the private scored episodes
    are reproducible from the aggregate file.  It rejects common raw-text,
    credential, request-linkage, and local-path fields before publication.
    """

    payload = _verify_analysis(analysis_path)
    findings: List[str] = []
    for item_path, key, value in _walk_json(payload):
        normalized_key = key.lower().replace("-", "_")
        if (
            normalized_key in _NONPUBLIC_ANALYSIS_KEYS
            or normalized_key.endswith(("_api_key", "_request_id", "_credential"))
            or (
                normalized_key.startswith(("prompt_", "response_", "question_"))
                and normalized_key not in _SAFE_AGGREGATE_TEXT_PREFIX_KEYS
            )
        ):
            findings.append("non-public key %s" % item_path)
        if isinstance(value, str):
            if _SECRET_SHAPE.search(value):
                findings.append("secret-shaped value %s" % item_path)
            if (
                _WINDOWS_ABSOLUTE_PATH.match(value)
                or _UNC_ABSOLUTE_PATH.match(value)
                or _POSIX_LOCAL_PATH.match(value)
            ):
                findings.append("local absolute path %s" % item_path)
    if findings:
        raise ValueError("aggregate analysis release boundary failed: " + "; ".join(findings))
    config_verified = False
    if config_path is not None:
        if file_sha256(config_path) != payload["config_raw_sha256"]:
            raise ValueError("analysis configuration raw hash mismatch")
        config_verified = True
    return {
        "analysis_path": str(analysis_path),
        "analysis_sha256": payload["analysis_sha256"],
        "raw_sha256": file_sha256(analysis_path),
        "episode_count": payload["episode_count"],
        "panel_count": len(payload["panels"]),
        "label_variant": payload["label_variant"],
        "config_verified": config_verified,
        "contains_prompt_or_response_text": False,
        "contains_credentials_or_request_ids": False,
        "reexecution_boundary": "aggregate-analysis-to-publication-artifacts",
    }


def verify_qualification_publication_bundle(
    *, bundle_dir: Path, analysis_paths: Sequence[Path] = ()
) -> Dict[str, Any]:
    """Verify publication manifest hashes, sidecars, and optional inputs."""

    manifest_path = bundle_dir / "publication-manifest.json"
    manifest = _load_object(manifest_path)
    claimed = manifest.get("manifest_sha256")
    candidate = copy.deepcopy(manifest)
    candidate.pop("manifest_sha256", None)
    if manifest.get("format") != MANIFEST_FORMAT or claimed != sha256_json(candidate):
        raise ValueError("qualification publication manifest identity mismatch")
    rows = manifest.get("artifacts")
    if not isinstance(rows, list) or not rows:
        raise ValueError("qualification publication manifest has no artifacts")
    registered: Dict[str, str] = {}
    for row in rows:
        relative = row.get("relative_path") if isinstance(row, dict) else None
        digest = row.get("sha256") if isinstance(row, dict) else None
        if (
            not isinstance(relative, str)
            or not relative
            or relative in registered
            or Path(relative).is_absolute()
            or ".." in Path(relative).parts
            or not isinstance(digest, str)
        ):
            raise ValueError("invalid or duplicate publication artifact path")
        registered[relative] = digest
        artifact = bundle_dir / Path(relative)
        if not artifact.is_file() or file_sha256(artifact) != digest:
            raise ValueError("publication artifact missing or drifted: %s" % relative)
    observed = {
        path.relative_to(bundle_dir).as_posix()
        for path in bundle_dir.rglob("*")
        if path.is_file() and path != manifest_path
    }
    if observed != set(registered):
        raise ValueError("publication bundle contains unregistered or missing files")
    if set(registered) != _EXPECTED_PUBLICATION_ARTIFACTS:
        raise ValueError("publication bundle does not contain the complete artifact set")
    data = _load_object(bundle_dir / "publication-data.json")
    data_candidate = copy.deepcopy(data)
    data_claimed = data_candidate.pop("data_sha256", None)
    if data.get("format") != DATA_FORMAT or data_claimed != sha256_json(data_candidate):
        raise ValueError("publication-data identity mismatch")
    if (
        data.get("analysis_inputs") != manifest.get("analysis_inputs")
        or data.get("tool_version") != manifest.get("tool_version")
        or data.get("system_ranking_computed") is not False
        or manifest.get("system_ranking_computed") is not False
    ):
        raise ValueError("publication data/manifest input mismatch")
    for sidecar in (bundle_dir / "figures").glob("*.manifest.json"):
        payload = _load_object(sidecar)
        sidecar_candidate = copy.deepcopy(payload)
        sidecar_claimed = sidecar_candidate.pop("manifest_sha256", None)
        output = bundle_dir / payload.get("output_relative_path", "")
        if (
            sidecar_claimed != sha256_json(sidecar_candidate)
            or not output.is_file()
            or file_sha256(output) != payload.get("output_sha256")
        ):
            raise ValueError("figure sidecar identity mismatch: %s" % sidecar.name)
    if analysis_paths:
        expected_inputs = []
        for path in analysis_paths:
            payload = _verify_analysis(path)
            expected_inputs.append(
                {
                    "label_variant": payload["label_variant"],
                    "analysis_sha256": payload["analysis_sha256"],
                    "raw_sha256": file_sha256(path),
                }
            )
        expected_inputs.sort(key=lambda item: item["label_variant"])
        if expected_inputs != manifest.get("analysis_inputs"):
            raise ValueError("publication bundle does not match supplied analyses")
    return {
        "status": "passed",
        "bundle_dir": str(bundle_dir),
        "artifact_count": len(registered),
        "manifest_sha256": claimed,
        "analysis_inputs_verified": bool(analysis_paths),
    }


def reproduce_and_compare_qualification_publication(
    *, analysis_paths: Sequence[Path], reference_dir: Path
) -> Dict[str, Any]:
    """Regenerate a bundle in a temporary directory and compare every byte."""

    verify_qualification_publication_bundle(bundle_dir=reference_dir, analysis_paths=analysis_paths)
    with tempfile.TemporaryDirectory(prefix="mathaudit-reproduce-") as temporary:
        generated = Path(temporary) / "publication"
        write_qualification_publication_bundle(output_dir=generated, analysis_paths=analysis_paths)
        verify_qualification_publication_bundle(bundle_dir=generated, analysis_paths=analysis_paths)
        expected_files = {
            path.relative_to(reference_dir).as_posix(): file_sha256(path)
            for path in reference_dir.rglob("*")
            if path.is_file()
        }
        generated_files = {
            path.relative_to(generated).as_posix(): file_sha256(path)
            for path in generated.rglob("*")
            if path.is_file()
        }
        if expected_files != generated_files:
            changed = sorted(
                path
                for path in set(expected_files) | set(generated_files)
                if expected_files.get(path) != generated_files.get(path)
            )
            raise ValueError(
                "publication reproduction differs from reference: %s" % ", ".join(changed)
            )
    return {
        "status": "passed",
        "reference_dir": str(reference_dir),
        "file_count": len(expected_files),
        "byte_identical": True,
        "analysis_count": len(analysis_paths),
    }


def _load_analyses(paths: Sequence[Path]) -> Dict[str, Dict[str, Any]]:
    if not paths:
        raise ValueError("at least one qualification analysis is required")
    analyses: Dict[str, Dict[str, Any]] = {}
    for path in paths:
        payload = _verify_analysis(path)
        variant = payload["label_variant"]
        if variant in analyses:
            raise ValueError("duplicate qualification label variant")
        analyses[variant] = payload
    if "deterministic" not in analyses:
        raise ValueError("deterministic qualification analysis is required")
    reference = analyses["deterministic"]
    reference_panels = [
        (item["panel_id"], item["system_id"], item["stratum"]) for item in reference["panels"]
    ]
    for payload in analyses.values():
        if (
            payload["source_plan_sha256"] != reference["source_plan_sha256"]
            or payload["config_raw_sha256"] != reference["config_raw_sha256"]
            or payload["analysis_config"] != reference["analysis_config"]
            or [
                (item["panel_id"], item["system_id"], item["stratum"]) for item in payload["panels"]
            ]
            != reference_panels
        ):
            raise ValueError("qualification analysis variants are not comparable")
    return analyses


def _flatten(value: Any, prefix: str = "") -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    if isinstance(value, dict):
        for key in sorted(value):
            child = "%s_%s" % (prefix, key) if prefix else str(key)
            result.update(_flatten(value[key], child))
    elif isinstance(value, list):
        if len(value) == 2 and all(
            item is None or isinstance(item, (int, float)) for item in value
        ):
            result[prefix + "_low"] = value[0]
            result[prefix + "_high"] = value[1]
        else:
            result[prefix] = json.dumps(value, ensure_ascii=False, sort_keys=True)
    else:
        result[prefix] = value
    return result


def _table_rows(analyses: Dict[str, Dict[str, Any]], panel_field: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for variant in sorted(analyses):
        for panel in analyses[variant]["panels"]:
            identity = {
                "label_variant": variant,
                "panel_id": panel["panel_id"],
                "system_id": panel["system_id"],
                "stratum": panel["stratum"],
                "episode_count": panel["episode_count"],
            }
            value = panel[panel_field]
            items = value if isinstance(value, list) else [value]
            rows.extend({**identity, **_flatten(item)} for item in items)
    return rows


def _write_csv(path: Path, rows: Sequence[Dict[str, Any]]) -> None:
    identity = ["label_variant", "panel_id", "system_id", "stratum", "episode_count"]
    fields = identity + sorted({key for row in rows for key in row}.difference(identity))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=fields, extrasaction="raise", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def _write_utf8(path: Path, text: str) -> None:
    """Write deterministic UTF-8 bytes with LF newlines on every platform."""
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def _svg(title: str, description: str, width: int, height: int, body: str) -> str:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" role="img" '
        'aria-labelledby="title description" viewBox="0 0 %d %d">'
        '<title id="title">%s</title><desc id="description">%s</desc>'
        '<rect width="100%%" height="100%%" fill="white"/>'
        "<style>text{font-family:Arial,sans-serif;fill:#172033}.title{font-size:18px;"
        "font-weight:700}.label{font-size:11px}.small{font-size:9px;fill:#4b5563}"
        ".axis{stroke:#94a3b8}.grid{stroke:#e2e8f0}</style>%s</svg>"
        % (width, height, html.escape(title), html.escape(description), body)
    )


def _rate_x(value: Any, left: int, right: int, low: float = 0.0, high: float = 1.0) -> Any:
    if value is None:
        return None
    return left + (float(value) - low) / (high - low) * (right - left)


def _axis(left: int, right: int, y: int, low: float = 0.0, high: float = 1.0) -> str:
    parts = ['<line class="axis" x1="%d" y1="%d" x2="%d" y2="%d"/>' % (left, y, right, y)]
    for index in range(5):
        fraction = index / 4
        x = left + fraction * (right - left)
        value = low + fraction * (high - low)
        parts.append(
            '<line class="grid" x1="%.1f" y1="%d" x2="%.1f" y2="%d"/>' % (x, y - 4, x, y + 4)
        )
        parts.append(
            '<text class="small" x="%.1f" y="%d" text-anchor="middle">%.2g</text>'
            % (x, y + 16, value)
        )
    return "".join(parts)


def _primary(analyses: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    return analyses.get("adjudicated", analyses["deterministic"])


def _availability_figure(analyses: Dict[str, Dict[str, Any]]) -> str:
    analysis = _primary(analyses)
    rows = [(panel, item) for panel in analysis["panels"] for item in panel["availability"]]
    width, left, right, step = 1180, 330, 1120, 28
    height = 90 + step * len(rows)
    colors = ["#0072B2", "#D55E00", "#009E73", "#CC79A7"]
    body = [
        '<text class="title" x="20" y="28">Availability before dependence</text>',
        '<circle cx="20" cy="50" r="4" fill="%s"/><text class="small" x="29" y="53">eligible</text>'
        % colors[0],
        '<circle cx="82" cy="50" r="4" fill="%s"/><text class="small" x="91" y="53">called</text>'
        % colors[1],
        '<circle cx="140" cy="50" r="4" fill="%s"/><text class="small" x="149" y="53">produced</text>'
        % colors[2],
        '<circle cx="220" cy="50" r="4" fill="%s"/><text class="small" x="229" y="53">binary scorable</text>'
        % colors[3],
        _axis(left, right, 52),
    ]
    for index, (panel, item) in enumerate(rows):
        y = 82 + index * step
        registered = item["registered_episodes"]
        denominators = item["episode_denominators"]
        values = [
            denominators["eligible"],
            denominators["called"],
            denominators["produced"],
            item["binary_scorable"],
        ]
        label = "%s · %s" % (panel["panel_id"], item["source_id"])
        body.append('<text class="label" x="20" y="%d">%s</text>' % (y + 3, html.escape(label)))
        for offset, (count, color) in enumerate(zip(values, colors, strict=True)):
            x = _rate_x(count / registered if registered else 0.0, left, right)
            body.append(
                '<circle cx="%.1f" cy="%d" r="4" fill="%s"><title>%d/%d</title></circle>'
                % (x, y + offset * 3 - 5, color, count, registered)
            )
    return _svg(
        "Availability before dependence",
        "Eligible, called, produced and binary-scorable proportions from the frozen qualification analysis.",
        width,
        height,
        "".join(body),
    )


def _dependence_figure(analyses: Dict[str, Dict[str, Any]]) -> str:
    analysis = _primary(analyses)
    rows = [
        (panel, item)
        for panel in analysis["panels"]
        for item in panel["source_type_pairwise"]
        if item["provenance_relation"] == "all"
    ]
    width, left, right, step = 1160, 380, 1100, 30
    height = 92 + step * len(rows)
    body = [
        '<text class="title" x="20" y="28">Episode-balanced error dependence</text>',
        '<line x1="20" y1="50" x2="52" y2="50" stroke="#0072B2" stroke-width="3"/>'
        '<circle cx="36" cy="50" r="5" fill="#D55E00"/>'
        '<text class="small" x="62" y="53">phi and cluster-bootstrap 95% interval</text>',
        _axis(left, right, 52, -1.0, 1.0),
    ]
    for index, (panel, item) in enumerate(rows):
        y = 82 + index * step
        label = "%s · %s–%s" % (panel["panel_id"], item["source_type_a"], item["source_type_b"])
        body.append('<text class="label" x="20" y="%d">%s</text>' % (y + 3, html.escape(label)))
        value = item["phi_episode_balanced"]
        x = _rate_x(value, left, right, -1.0, 1.0)
        interval = item["phi_cluster_bootstrap_95"]
        if x is None:
            body.append('<text class="small" x="%d" y="%d">NA</text>' % (left, y + 3))
        else:
            low = _rate_x(interval[0], left, right, -1.0, 1.0)
            high = _rate_x(interval[1], left, right, -1.0, 1.0)
            if low is not None and high is not None:
                body.append(
                    '<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" stroke="#0072B2" stroke-width="3"/>'
                    % (low, y, high, y)
                )
            body.append('<circle cx="%.1f" cy="%d" r="5" fill="#D55E00"/>' % (x, y))
    return _svg(
        "Episode-balanced error dependence",
        "Primary source-type phi with episode-cluster bootstrap intervals; all-provenance facet only.",
        width,
        height,
        "".join(body),
    )


def _transition_figure(analyses: Dict[str, Dict[str, Any]]) -> str:
    analysis = _primary(analyses)
    rows = [(panel, item) for panel in analysis["panels"] for item in panel["transitions"]]
    width, left, right, step = 1160, 360, 1100, 32
    height = 92 + step * max(1, len(rows))
    body = [
        '<text class="title" x="20" y="28">Repair and harm realizations</text>',
        '<circle cx="20" cy="50" r="5" fill="#009E73"/><text class="small" x="30" y="53">repair realization</text>',
        '<circle cx="155" cy="50" r="5" fill="#D55E00"/><text class="small" x="165" y="53">harm realization</text>',
        _axis(left, right, 52),
    ]
    for index, (panel, item) in enumerate(rows):
        y = 82 + index * step
        label = "%s · %s→%s" % (panel["panel_id"], item["upstream"], item["checker"])
        body.append('<text class="label" x="20" y="%d">%s</text>' % (y + 3, html.escape(label)))
        for offset, (field, color) in enumerate(
            (("repair_realization_rate", "#009E73"), ("harm_realization_rate", "#D55E00"))
        ):
            x = _rate_x(item[field], left, right)
            if x is not None:
                body.append(
                    '<circle cx="%.1f" cy="%d" r="5" fill="%s"><title>%s</title></circle>'
                    % (x, y + offset * 6 - 3, color, field)
                )
    return _svg(
        "Repair and harm realizations",
        "Descriptive directed transition realization rates from preregistered stable directions.",
        width,
        height,
        "".join(body),
    )


def _repetition_figure(analyses: Dict[str, Dict[str, Any]]) -> str:
    analysis = _primary(analyses)
    rows = [(panel, item) for panel in analysis["panels"] for item in panel["text_repetition"]]
    width, left, right, step = 1160, 360, 1100, 32
    height = 92 + step * max(1, len(rows))
    body = [
        '<text class="title" x="20" y="28">Exact validation repetition</text>',
        '<circle cx="20" cy="50" r="4" fill="#0072B2"/><text class="small" x="29" y="53">content hash</text>',
        '<circle cx="116" cy="50" r="4" fill="#CC79A7"/><text class="small" x="125" y="53">normalized text</text>',
        '<circle cx="235" cy="50" r="4" fill="#E69F00"/><text class="small" x="244" y="53">normalized answer</text>',
        _axis(left, right, 52),
    ]
    for index, (panel, item) in enumerate(rows):
        y = 82 + index * step
        label = "%s · %s→%s" % (panel["panel_id"], item["source_a"], item["source_b"])
        body.append('<text class="label" x="20" y="%d">%s</text>' % (y + 3, html.escape(label)))
        for offset, (field, color) in enumerate(
            (
                ("identical_content_hash_rate", "#0072B2"),
                ("exact_text_repeat_rate", "#CC79A7"),
                ("exact_normalized_answer_repeat_rate", "#E69F00"),
            )
        ):
            x = _rate_x(item[field], left, right)
            if x is not None:
                body.append(
                    '<circle cx="%.1f" cy="%d" r="4" fill="%s"><title>%s</title></circle>'
                    % (x, y + offset * 4 - 4, color, field)
                )
    return _svg(
        "Exact validation repetition",
        "Content-hash, normalized full-text and normalized-answer exact repetition; no semantic equivalence is inferred.",
        width,
        height,
        "".join(body),
    )


def write_qualification_publication_bundle(
    *, output_dir: Path, analysis_paths: Sequence[Path]
) -> Dict[str, Any]:
    """Write tables and figures from self-hashed six-panel analysis artifacts."""

    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError("qualification publication output must be absent or empty")
    analyses = _load_analyses(analysis_paths)
    output_dir.mkdir(parents=True, exist_ok=True)
    reference = analyses["deterministic"]
    input_rows = []
    for path in analysis_paths:
        payload = _verify_analysis(path)
        input_rows.append(
            {
                "label_variant": payload["label_variant"],
                "analysis_sha256": payload["analysis_sha256"],
                "raw_sha256": file_sha256(path),
            }
        )
    input_rows.sort(key=lambda item: item["label_variant"])
    fields = (
        "availability",
        "cost",
        "exact_pairwise",
        "source_type_pairwise",
        "cofailure",
        "transitions",
        "utilization",
        "text_repetition",
        "effective_support",
        "final_outcomes",
    )
    table_paths: List[Path] = []
    table_counts: Dict[str, int] = {}
    for field in fields:
        rows = _table_rows(analyses, field)
        path = output_dir / "tables" / (field + ".csv")
        _write_csv(path, rows)
        table_paths.append(path)
        table_counts[field] = len(rows)
    figures = {
        "availability.svg": _availability_figure(analyses),
        "dependence.svg": _dependence_figure(analyses),
        "repair_harm.svg": _transition_figure(analyses),
        "repetition.svg": _repetition_figure(analyses),
    }
    figure_paths: List[Path] = []
    for name, content in figures.items():
        path = output_dir / "figures" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        _write_utf8(path, content + "\n")
        figure_paths.append(path)
    data = {
        "format": DATA_FORMAT,
        "tool_version": __version__,
        "source_plan_sha256": reference["source_plan_sha256"],
        "analysis_config_raw_sha256": reference["config_raw_sha256"],
        "label_variants": sorted(analyses),
        "analysis_inputs": input_rows,
        "table_row_counts": table_counts,
        "primary_figure_label_variant": (
            "adjudicated" if "adjudicated" in analyses else "deterministic"
        ),
        "system_ranking_computed": False,
    }
    data["data_sha256"] = sha256_json(data)
    data_path = output_dir / "publication-data.json"
    _write_utf8(data_path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    command = "mathaudit qualification-publish --analysis ANALYSIS [--analysis ANALYSIS] --output-dir OUTPUT_DIR"
    sidecars: List[Path] = []
    for figure in figure_paths:
        sidecar = figure.with_suffix(figure.suffix + ".manifest.json")
        payload = {
            "format": "mathaudit-qualification-figure-manifest-v0.1",
            "tool_version": __version__,
            "source_plan_sha256": reference["source_plan_sha256"],
            "analysis_inputs": input_rows,
            "command": command,
            "output_relative_path": figure.relative_to(output_dir).as_posix(),
            "output_sha256": file_sha256(figure),
        }
        payload["manifest_sha256"] = sha256_json(payload)
        _write_utf8(sidecar, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        sidecars.append(sidecar)
    artifacts = [data_path, *table_paths, *figure_paths, *sidecars]
    manifest = {
        "format": MANIFEST_FORMAT,
        "tool_version": __version__,
        "source_plan_sha256": reference["source_plan_sha256"],
        "analysis_config_raw_sha256": reference["config_raw_sha256"],
        "label_variants": sorted(analyses),
        "analysis_inputs": input_rows,
        "command": command,
        "artifacts": [
            {
                "relative_path": path.relative_to(output_dir).as_posix(),
                "sha256": file_sha256(path),
            }
            for path in sorted(artifacts, key=lambda item: item.relative_to(output_dir).as_posix())
        ],
        "system_ranking_computed": False,
    }
    manifest["manifest_sha256"] = sha256_json(manifest)
    _write_utf8(
        output_dir / "publication-manifest.json",
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
    )
    return manifest
