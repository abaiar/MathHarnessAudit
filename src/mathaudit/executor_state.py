"""Versioned qualification executor-state migration helpers."""

from __future__ import annotations

import copy
from typing import Any, Dict

from .hashing import sha256_json

STATE_FORMAT_V01 = "mathaudit-qualification-executor-state-v0.1"
STATE_FORMAT_V02 = "mathaudit-qualification-executor-state-v0.2"
STATE_FORMAT_V03 = "mathaudit-qualification-executor-state-v0.3"
STATE_FORMAT_V04 = "mathaudit-qualification-executor-state-v0.4"
LEGACY_STATE_FORMATS = {STATE_FORMAT_V01, STATE_FORMAT_V02}


def verify_executor_state_self_hash(payload: Dict[str, Any]) -> None:
    """Verify the embedded state hash without changing the supplied object."""

    claimed = payload.get("state_sha256")
    candidate = copy.deepcopy(payload)
    candidate.pop("state_sha256", None)
    if claimed != sha256_json(candidate):
        raise ValueError("executor state self-hash mismatch")


def migrate_executor_state_v03(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Return a provenance-preserving v0.3 copy of a terminal v0.1/v0.2 state."""

    if not isinstance(payload, dict):
        raise ValueError("executor state must be an object")
    verify_executor_state_self_hash(payload)
    source_format = payload.get("format")
    if source_format in {STATE_FORMAT_V03, STATE_FORMAT_V04}:
        return copy.deepcopy(payload)
    if source_format not in LEGACY_STATE_FORMATS:
        raise ValueError("unsupported qualification executor state")
    if payload.get("status") not in {
        "completed",
        "stopped_failure",
        "stopped_wall_cap",
    }:
        raise ValueError("only terminal executor states may be migrated")

    result = copy.deepcopy(payload)
    source_hash = str(result.pop("state_sha256"))
    result["format"] = STATE_FORMAT_V03
    if source_format == STATE_FORMAT_V01:
        current = result.pop("current_episode", None)
        result["current_episodes"] = [] if current is None else [current]
    current_episodes = result.get("current_episodes")
    if current_episodes:
        raise ValueError("terminal executor state contains unfinished episodes")

    terminal_at = result.get("ended_at") or result.get("updated_at")
    if not isinstance(terminal_at, str) or not terminal_at:
        raise ValueError("terminal executor state has no terminal timestamp")
    episodes = result.get("episodes")
    if not isinstance(episodes, list):
        raise ValueError("executor state episodes must be a list")
    for episode in episodes:
        if not isinstance(episode, dict):
            raise ValueError("executor state episode must be an object")
        episode.setdefault("output_relative_path", None)
        episode.setdefault("ended_at", terminal_at)
        attempts = episode.get("attempts")
        if not isinstance(attempts, list):
            raise ValueError("executor state episode attempts must be a list")
        for attempt in attempts:
            if not isinstance(attempt, dict):
                raise ValueError("executor attempt must be an object")
            attempt.setdefault("return_code", None)

    result["migrated_from"] = {
        "format": source_format,
        "state_sha256": source_hash,
    }
    result["state_sha256"] = sha256_json(result)
    return result
