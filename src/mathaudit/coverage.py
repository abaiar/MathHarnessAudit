# SPDX-License-Identifier: MIT

"""Adapter fidelity and observability summaries."""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, Iterable

from .models import Episode, ObservationOutcome
from .validation import validate_episode


def adapter_coverage(episodes: Iterable[Episode]) -> Dict[str, Any]:
    episodes = list(episodes)
    fidelity = Counter(episode.adapter.fidelity.value for episode in episodes)
    outcomes = Counter(
        observation.outcome.value
        for episode in episodes
        for observation in episode.source_observations
    )
    kinds = Counter(item.kind.value for episode in episodes for item in episode.evidence)
    decision_types = Counter(
        decision.decision_type.value for episode in episodes for decision in episode.decisions
    )
    semantic_issues = Counter(
        issue.code for episode in episodes for issue in validate_episode(episode)
    )
    selections = sum(
        1
        for episode in episodes
        for decision in episode.decisions
        if decision.selected_evidence_ids
    )
    decisions = sum(len(episode.decisions) for episode in episodes)
    produced = outcomes.get(ObservationOutcome.produced.value, 0)
    observations = sum(outcomes.values())
    return {
        "episodes": len(episodes),
        "adapter_names": sorted({episode.adapter.name for episode in episodes}),
        "fidelity": dict(sorted(fidelity.items())),
        "source_observations": observations,
        "observation_outcomes": dict(sorted(outcomes.items())),
        "production_fraction": (produced / observations) if observations else None,
        "evidence_items": sum(kinds.values()),
        "evidence_kinds": dict(sorted(kinds.items())),
        "decisions": decisions,
        "decision_types": dict(sorted(decision_types.items())),
        "decisions_with_observed_selection": selections,
        "semantic_issues": dict(sorted(semantic_issues.items())),
    }
