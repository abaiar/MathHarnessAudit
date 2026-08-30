"""Optional Parquet export of normalized canonical tables."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

import pandas as pd

from .models import Episode


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _write_rows(path: Path, rows: List[Dict[str, Any]]) -> None:
    frame = (
        pd.DataFrame(rows)
        if rows
        else pd.DataFrame({"episode_id": pd.Series(dtype="string")})
    )
    frame.to_parquet(path, index=False)


def write_parquet_bundle(output_dir: Path, episodes: Iterable[Episode]) -> List[Path]:
    """Write episode, source, observation, evidence, decision, edge, and label tables."""

    try:
        import pyarrow  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "Parquet export requires the optional dependency: pip install math-harness-audit[parquet]"
        ) from exc

    episodes = list(episodes)
    output_dir.mkdir(parents=True, exist_ok=True)
    tables: Dict[str, List[Dict[str, Any]]] = {
        "episodes": [],
        "sources": [],
        "source_observations": [],
        "evidence": [],
        "decisions": [],
        "provenance_edges": [],
        "labels": [],
    }
    for episode in episodes:
        episode_id = episode.episode_id
        tables["episodes"].append(
            {
                "episode_id": episode_id,
                "schema_version": episode.schema_version,
                "problem_id": episode.problem.problem_id,
                "dataset_id": episode.problem.dataset_id,
                "split": episode.problem.split,
                "stratum": episode.problem.stratum,
                "system_id": episode.system.system_id,
                "system_version": episode.system.version,
                "run_id": episode.run.run_id,
                "adapter_name": episode.adapter.name,
                "adapter_version": episode.adapter.version,
                "adapter_fidelity": episode.adapter.fidelity.value,
                "final_status": episode.final_output.status.value,
                "final_evidence_id": episode.final_output.evidence_id,
                "metadata_json": _json(episode.metadata),
            }
        )
        for source in episode.sources:
            row = source.model_dump(mode="json", exclude_none=False)
            row["episode_id"] = episode_id
            row["metadata_json"] = _json(row.pop("metadata"))
            tables["sources"].append(row)
        for observation in episode.source_observations:
            row = observation.model_dump(mode="json", exclude_none=False)
            row["episode_id"] = episode_id
            row["cost_json"] = _json(row.pop("cost"))
            row["metadata_json"] = _json(row.pop("metadata"))
            tables["source_observations"].append(row)
        for item in episode.evidence:
            row = item.model_dump(mode="json", exclude_none=False)
            row["episode_id"] = episode_id
            content = row.pop("content")
            row.update(
                {
                    "visibility": content["visibility"],
                    "text": content["text"],
                    "content_hash": content["content_hash"]["value"],
                    "normalized_answer": content["normalized_answer"],
                    "structured_json": _json(content["structured"]),
                    "metadata_json": _json(row.pop("metadata")),
                }
            )
            tables["evidence"].append(row)
        for decision in episode.decisions:
            row = decision.model_dump(mode="json", exclude_none=False)
            row["episode_id"] = episode_id
            for key in (
                "input_evidence_ids",
                "candidate_evidence_ids",
                "selected_evidence_ids",
                "output_evidence_ids",
                "cost",
                "metadata",
            ):
                row["%s_json" % key] = _json(row.pop(key))
            tables["decisions"].append(row)
        for edge in episode.provenance_edges:
            row = edge.model_dump(mode="json", exclude_none=False)
            row["episode_id"] = episode_id
            row["metadata_json"] = _json(row.pop("metadata"))
            tables["provenance_edges"].append(row)
        for label in episode.labels:
            row = label.model_dump(mode="json", exclude_none=False)
            row["episode_id"] = episode_id
            row["decision_path_json"] = _json(row.pop("decision_path"))
            row["metadata_json"] = _json(row.pop("metadata"))
            tables["labels"].append(row)

    paths: List[Path] = []
    for name, rows in tables.items():
        path = output_dir / (name + ".parquet")
        _write_rows(path, rows)
        paths.append(path)
    return paths
