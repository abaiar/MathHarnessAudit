# SPDX-License-Identifier: MIT

from mathaudit.models import (
    EdgeObservability,
    EdgeRelation,
    FinalOutput,
    FinalStatus,
    Invocation,
    ObservationOutcome,
    ProvenanceEdge,
)
from mathaudit.validation import validate_episode


def issue_codes(episode):
    return {issue.code for issue in validate_episode(episode)}


def test_valid_oracle_episode_has_no_issues(episode_factory):
    assert validate_episode(episode_factory(0, True, True, True)) == []


def test_duplicate_ids_are_rejected(episode_factory):
    episode = episode_factory(0, True, True, True)
    episode.sources.append(episode.sources[0].model_copy(deep=True))
    assert "duplicate_id" in issue_codes(episode)


def test_evidence_requires_produced_observation(episode_factory):
    episode = episode_factory(0, True, True, True)
    episode.source_observations[0].outcome = ObservationOutcome.no_vote
    assert "evidence_without_production" in issue_codes(episode)


def test_not_called_is_not_allowed_to_produce(episode_factory):
    episode = episode_factory(0, True, True, True)
    episode.source_observations[0].invocation = Invocation.not_called
    assert "not_called_produced" in issue_codes(episode)


def test_derivation_cycle_is_rejected(episode_factory):
    episode = episode_factory(0, True, True, True)
    episode.provenance_edges = [
        ProvenanceEdge(from_id="ev:a:0", to_id="ev:b:0", relation=EdgeRelation.derived_from, observability=EdgeObservability.observed),
        ProvenanceEdge(from_id="ev:b:0", to_id="ev:a:0", relation=EdgeRelation.derived_from, observability=EdgeObservability.observed),
    ]
    assert "provenance_cycle" in issue_codes(episode)


def test_final_output_must_reference_final_evidence(episode_factory):
    episode = episode_factory(0, True, True, True)
    episode.final_output = FinalOutput(status=FinalStatus.produced, evidence_id="ev:a:0")
    assert "wrong_final_kind" in issue_codes(episode)


def test_gold_key_in_solver_metadata_is_rejected(episode_factory):
    episode = episode_factory(0, True, True, True)
    episode.problem.solver_visible_metadata["gold_answer"] = "1"
    assert "gold_leak" in issue_codes(episode)
