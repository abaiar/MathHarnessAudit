# SPDX-License-Identifier: MIT

"""Pass-through adapter for already canonical records."""

from __future__ import annotations

from typing import Any, Dict

from ..models import Episode
from .base import ProblemContext, RunContext


class CanonicalAdapter:
    name = "canonical"
    version = "1.0.0"

    def can_handle(self, payload: Dict[str, Any]) -> bool:
        return payload.get("schema_version") in {"0.1", "1.0"} and "episode_id" in payload

    def convert(
        self,
        payload: Dict[str, Any],
        problem: ProblemContext,
        run: RunContext,
    ) -> Episode:
        del problem, run
        return Episode.model_validate(payload)
