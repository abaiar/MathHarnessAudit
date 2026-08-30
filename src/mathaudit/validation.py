# SPDX-License-Identifier: MIT

"""Semantic validation for canonical episodes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Set

from .models import (
    EdgeRelation,
    Episode,
    EvidenceKind,
    FinalStatus,
    Invocation,
    ObservationOutcome,
)


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    path: str
    message: str
    severity: str = "error"


def _duplicates(values: Iterable[str]) -> Set[str]:
    seen: Set[str] = set()
    duplicate: Set[str] = set()
    for value in values:
        if value in seen:
            duplicate.add(value)
        seen.add(value)
    return duplicate


def _contains_forbidden_gold_key(value: Any) -> bool:
    forbidden = {"gold", "gold_answer", "reference_answer", "ground_truth"}
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = str(key).strip().lower().replace("-", "_")
            if normalized in forbidden or _contains_forbidden_gold_key(nested):
                return True
    elif isinstance(value, list):
        return any(_contains_forbidden_gold_key(item) for item in value)
    return False


def _has_derivation_cycle(episode: Episode) -> bool:
    relations = {EdgeRelation.derived_from, EdgeRelation.aggregates, EdgeRelation.produces}
    graph: Dict[str, List[str]] = {}
    for edge in episode.provenance_edges:
        if edge.relation in relations:
            graph.setdefault(edge.from_id, []).append(edge.to_id)

    visiting: Set[str] = set()
    visited: Set[str] = set()

    def visit(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        for child in graph.get(node, []):
            if visit(child):
                return True
        visiting.remove(node)
        visited.add(node)
        return False

    return any(visit(node) for node in list(graph))


def validate_episode(episode: Episode) -> List[ValidationIssue]:
    """Return every semantic issue found in an already parsed episode."""

    issues: List[ValidationIssue] = []

    id_groups = {
        "sources": [item.source_id for item in episode.sources],
        "source_observations": [item.observation_id for item in episode.source_observations],
        "evidence": [item.evidence_id for item in episode.evidence],
        "decisions": [item.decision_id for item in episode.decisions],
        "labels": [item.label_id for item in episode.labels],
    }
    for group, values in id_groups.items():
        for duplicate in sorted(_duplicates(values)):
            issues.append(
                ValidationIssue("duplicate_id", group, "duplicate ID: %s" % duplicate)
            )

    source_ids = set(id_groups["sources"])
    observation_map = {
        item.observation_id: item for item in episode.source_observations
    }
    evidence_map = {item.evidence_id: item for item in episode.evidence}
    decision_ids = set(id_groups["decisions"])
    node_ids = set(evidence_map) | decision_ids

    for index, observation in enumerate(episode.source_observations):
        path = "source_observations[%d]" % index
        if observation.source_id not in source_ids:
            issues.append(
                ValidationIssue("unknown_source", path + ".source_id", observation.source_id)
            )
        if observation.invocation == Invocation.not_called:
            if observation.outcome == ObservationOutcome.produced:
                issues.append(
                    ValidationIssue(
                        "not_called_produced",
                        path,
                        "a not-called source cannot produce evidence",
                    )
                )
            if observation.cost.calls not in (None, 0):
                issues.append(
                    ValidationIssue(
                        "not_called_cost",
                        path + ".cost.calls",
                        "a not-called source cannot have positive call count",
                    )
                )

    for index, evidence in enumerate(episode.evidence):
        path = "evidence[%d]" % index
        observation = observation_map.get(evidence.observation_id)
        if observation is None:
            issues.append(
                ValidationIssue(
                    "unknown_observation", path + ".observation_id", evidence.observation_id
                )
            )
        elif observation.outcome != ObservationOutcome.produced:
            issues.append(
                ValidationIssue(
                    "evidence_without_production",
                    path + ".observation_id",
                    "evidence requires an observation with outcome=produced",
                )
            )

    for index, decision in enumerate(episode.decisions):
        path = "decisions[%d]" % index
        referenced = (
            decision.input_evidence_ids
            + decision.candidate_evidence_ids
            + decision.selected_evidence_ids
            + decision.output_evidence_ids
        )
        for evidence_id in referenced:
            if evidence_id not in evidence_map:
                issues.append(
                    ValidationIssue(
                        "unknown_decision_evidence", path, "unknown evidence ID: %s" % evidence_id
                    )
                )
        allowed_selection = set(decision.input_evidence_ids) | set(
            decision.candidate_evidence_ids
        )
        if not set(decision.selected_evidence_ids).issubset(allowed_selection):
            issues.append(
                ValidationIssue(
                    "selection_not_candidate",
                    path + ".selected_evidence_ids",
                    "selected evidence must be an input or candidate",
                )
            )

    for index, edge in enumerate(episode.provenance_edges):
        path = "provenance_edges[%d]" % index
        if edge.from_id not in node_ids:
            issues.append(ValidationIssue("unknown_edge_source", path + ".from_id", edge.from_id))
        if edge.to_id not in node_ids:
            issues.append(ValidationIssue("unknown_edge_target", path + ".to_id", edge.to_id))

    if _has_derivation_cycle(episode):
        issues.append(
            ValidationIssue(
                "provenance_cycle",
                "provenance_edges",
                "derivation/aggregation/production relations must be acyclic",
            )
        )

    for index, label in enumerate(episode.labels):
        if label.target_type == "episode":
            valid = label.target_id == episode.episode_id
        else:
            valid = label.target_id in evidence_map
        if not valid:
            issues.append(
                ValidationIssue(
                    "unknown_label_target", "labels[%d].target_id" % index, label.target_id
                )
            )

    if episode.final_output.status == FinalStatus.produced:
        final_id = episode.final_output.evidence_id
        final_evidence = evidence_map.get(final_id or "")
        if final_evidence is None:
            issues.append(
                ValidationIssue(
                    "missing_final_evidence",
                    "final_output.evidence_id",
                    "produced final output must reference evidence",
                )
            )
        elif final_evidence.kind != EvidenceKind.final_answer:
            issues.append(
                ValidationIssue(
                    "wrong_final_kind",
                    "final_output.evidence_id",
                    "final output evidence must have kind=final_answer",
                )
            )
    elif episode.final_output.evidence_id is not None:
        issues.append(
            ValidationIssue(
                "unexpected_final_evidence",
                "final_output.evidence_id",
                "non-produced final output cannot reference evidence",
            )
        )

    if _contains_forbidden_gold_key(episode.problem.solver_visible_metadata):
        issues.append(
            ValidationIssue(
                "gold_leak",
                "problem.solver_visible_metadata",
                "solver-visible metadata contains a prohibited gold key",
            )
        )

    return issues


def require_valid_episode(episode: Episode) -> Episode:
    """Raise a readable error if semantic validation fails."""

    issues = [issue for issue in validate_episode(episode) if issue.severity == "error"]
    if issues:
        detail = "; ".join("%s at %s: %s" % (i.code, i.path, i.message) for i in issues)
        raise ValueError(detail)
    return episode
