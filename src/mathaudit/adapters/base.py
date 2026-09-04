# SPDX-License-Identifier: MIT

"""Adapter interface and shared context."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Protocol

from ..models import Episode


@dataclass(frozen=True)
class ProblemContext:
    problem_id: str
    dataset_id: str
    split: str
    stratum: str
    statement: str
    gold: Optional[str] = None
    dataset_version: Optional[str] = None
    domain: Optional[str] = None
    difficulty: Optional[str] = None
    answer_type: Optional[str] = None
    solver_visible_metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RunContext:
    run_id: str
    system_id: str
    system_name: str
    system_version: str
    config: Dict[str, Any] = field(default_factory=dict)
    environment: Dict[str, Any] = field(default_factory=dict)
    harness_family: Optional[str] = None
    repository: Optional[str] = None
    commit: Optional[str] = None
    seed: Optional[int] = None


class Adapter(Protocol):
    name: str
    version: str

    def can_handle(self, payload: Dict[str, Any]) -> bool: ...

    def convert(
        self,
        payload: Dict[str, Any],
        problem: ProblemContext,
        run: RunContext,
    ) -> Episode: ...
