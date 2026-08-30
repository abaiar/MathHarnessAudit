# SPDX-License-Identifier: MIT

"""Trace ingestion orchestration shared by the CLI and tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

from .adapters import BUILTIN_ADAPTERS, ProblemContext, RunContext
from .hashing import sha256_json
from .models import Episode
from .validation import require_valid_episode


def get_adapter(name: str):
    for adapter in BUILTIN_ADAPTERS:
        if adapter.name == name:
            return adapter
    available = ", ".join(adapter.name for adapter in BUILTIN_ADAPTERS)
    raise ValueError("unknown adapter %r; choose one of: %s" % (name, available))


def iter_payloads(
    path: Path, pattern: Optional[str] = None
) -> Iterator[Tuple[Dict[str, Any], str]]:
    if path.is_dir():
        selected = pattern or "*.json"
        for child in sorted(path.glob(selected), key=lambda item: item.name):
            for payload, locator in iter_payloads(child):
                yield payload, locator
        return
    if path.suffix.lower() == ".jsonl":
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                payload = json.loads(line)
                if not isinstance(payload, dict):
                    raise ValueError("%s:%d is not a JSON object" % (path, line_number))
                yield payload, "%s:%d" % (path.name, line_number)
        return
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if isinstance(payload, list):
        for index, item in enumerate(payload):
            if not isinstance(item, dict):
                raise ValueError("%s[%d] is not a JSON object" % (path, index))
            yield item, "%s[%d]" % (path.name, index)
    elif isinstance(payload, dict):
        yield payload, path.name
    else:
        raise ValueError("%s must contain a JSON object or array" % path)


def _record_key(record: Dict[str, Any]) -> str:
    for key in ("idx", "id", "problem_id"):
        if key in record:
            return str(record[key])
    raise ValueError("record has no idx, id, or problem_id")


def load_problem_manifest(
    path: Path,
    *,
    dataset_id: str,
    split: str,
    stratum: str,
    dataset_version: Optional[str] = None,
) -> Dict[str, ProblemContext]:
    contexts: Dict[str, ProblemContext] = {}
    for record, locator in iter_payloads(path):
        key = _record_key(record)
        statement = str(record.get("problem") or record.get("question") or "").strip()
        if not statement:
            raise ValueError("%s has no problem/question text" % locator)
        gold_value = record.get("answer")
        if gold_value is None:
            gold_value = record.get("gold")
        gold = None if gold_value is None else str(gold_value)
        metadata = {
            name: value
            for name, value in record.items()
            if name
            not in {
                "answer",
                "gold",
                "gold_answer",
                "reference_answer",
                "ground_truth",
                "solution",
                "reference_solution",
                "proof",
                "problem",
                "question",
            }
        }
        domain_value = record.get("subject") or record.get("domain")
        if isinstance(domain_value, list):
            domain = " | ".join(str(item) for item in domain_value)
        elif domain_value is None:
            domain = None
        else:
            domain = str(domain_value)
        public_problem_id = record.get("public_problem_id")
        resolved_dataset_id = str(record.get("source_dataset_id") or dataset_id)
        resolved_dataset_version = record.get("source_dataset_version") or dataset_version
        resolved_stratum = str(record.get("source_stratum") or record.get("stratum") or stratum)
        contexts[key] = ProblemContext(
            problem_id=(
                str(public_problem_id) if public_problem_id else "%s#%s" % (dataset_id, key)
            ),
            dataset_id=resolved_dataset_id,
            dataset_version=(
                None if resolved_dataset_version is None else str(resolved_dataset_version)
            ),
            split=split,
            stratum=resolved_stratum,
            statement=statement,
            gold=gold,
            domain=domain,
            difficulty=None if record.get("difficulty") is None else str(record.get("difficulty")),
            answer_type=None if record.get("answer_type") is None else str(record.get("answer_type")),
            solver_visible_metadata=metadata,
        )
    return contexts


def ingest_payloads(
    payloads: Iterable[Tuple[Dict[str, Any], str]],
    *,
    adapter_name: str,
    problems: Dict[str, ProblemContext],
    run: RunContext,
    limit: Optional[int] = None,
) -> List[Episode]:
    adapter = get_adapter(adapter_name)
    episodes: List[Episode] = []
    for payload, locator in payloads:
        if limit is not None and len(episodes) >= limit:
            break
        key = _record_key(payload)
        if key not in problems:
            raise KeyError("%s references problem %s absent from manifest" % (locator, key))
        if not adapter.can_handle(payload):
            raise ValueError("adapter %s rejected %s" % (adapter_name, locator))
        episode = adapter.convert(payload, problems[key], run)
        episode.metadata.setdefault("ingest", {})
        episode.metadata["ingest"].update(
            {"source_locator": locator, "payload_sha256": sha256_json(payload)}
        )
        require_valid_episode(episode)
        episodes.append(episode)
    return episodes
