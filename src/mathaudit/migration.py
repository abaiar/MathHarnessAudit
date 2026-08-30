# SPDX-License-Identifier: MIT

"""Explicit migrations for stable public canonical contracts."""

from __future__ import annotations

from typing import Any, Mapping

from .models import Episode
from .validation import validate_episode

EPISODE_V01 = "0.1"
EPISODE_V10 = "1.0"


def migrate_episode_v1(payload: Episode | Mapping[str, Any]) -> Episode:
    """Return a semantically validated v1.0 episode without mutating the input.

    Canonical episode v1.0 freezes the field meanings used by v0.1. Migration is
    deliberately lossless: the only serialized-field change is
    ``schema_version``. Historical v0.1 files remain readable and retain their
    original bytes until a caller explicitly requests migration.
    """

    if isinstance(payload, Episode):
        document = payload.model_dump(mode="json")
    else:
        document = dict(payload)

    version = document.get("schema_version")
    if version not in {EPISODE_V01, EPISODE_V10}:
        raise ValueError("episode schema_version must be 0.1 or 1.0")

    migrated = dict(document)
    migrated["schema_version"] = EPISODE_V10
    episode = Episode.model_validate(migrated)
    issues = validate_episode(episode)
    if issues:
        details = "; ".join(f"{issue.code}: {issue.message}" for issue in issues)
        raise ValueError(f"episode is structurally valid but semantically invalid: {details}")
    return episode
