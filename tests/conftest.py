from datetime import datetime, timezone

import pytest

from mathaudit.adapters.common import hash_json, hash_text, make_content
from mathaudit.models import (
    AdapterFidelity,
    AdapterInfo,
    AdjudicationStatus,
    AuditOnly,
    Episode,
    Evidence,
    EvidenceKind,
    FinalOutput,
    FinalStatus,
    Invocation,
    LabelValue,
    ObservationOutcome,
    Opportunity,
    OutcomeLabel,
    Problem,
    Run,
    ScorerType,
    Source,
    SourceObservation,
    SourceType,
    System,
)

FIXED_TIME = datetime(2026, 8, 22, tzinfo=timezone.utc)


def build_episode(index, a, b, final, *, group_a="group_a", group_b="group_b"):
    values = {"a": a, "b": b, "final": final}
    source_specs = {
        "a": (SourceType.llm, group_a),
        "b": (SourceType.python, group_b),
        "final": (SourceType.composite, "finalizer"),
    }
    sources = []
    observations = []
    evidence = []
    labels = []
    for sequence, source_id in enumerate(("a", "b", "final")):
        sources.append(
            Source(
                source_id=source_id,
                source_type=source_specs[source_id][0],
                role=source_id,
                provenance_group=source_specs[source_id][1],
            )
        )
        observation_id = "obs:%s:%d" % (source_id, index)
        evidence_id = "ev:%s:%d" % (source_id, index)
        observations.append(
            SourceObservation(
                observation_id=observation_id,
                source_id=source_id,
                stage=source_id,
                sequence=sequence,
                opportunity=Opportunity.eligible,
                invocation=Invocation.called,
                outcome=ObservationOutcome.produced,
            )
        )
        evidence.append(
            Evidence(
                evidence_id=evidence_id,
                observation_id=observation_id,
                kind=EvidenceKind.final_answer if source_id == "final" else EvidenceKind.candidate_answer,
                stage=source_id,
                sequence=sequence,
                content=make_content("1" if values[source_id] else "0"),
            )
        )
        labels.append(
            OutcomeLabel(
                label_id="label:%s:%d" % (source_id, index),
                target_type="evidence",
                target_id=evidence_id,
                value=LabelValue.correct if values[source_id] else LabelValue.incorrect,
                scorer_type=ScorerType.exact,
                scorer_name="oracle",
                scorer_version="1",
                rule_id="synthetic",
                decision_path=["oracle"],
                confidence=1.0,
                adjudication_status=AdjudicationStatus.not_needed,
                created_at=FIXED_TIME,
            )
        )
    return Episode(
        episode_id="episode:%d" % index,
        problem=Problem(
            problem_id="synthetic#%d" % index,
            dataset_id="synthetic",
            split="test",
            stratum="oracle",
            input_hash=hash_text("problem %d" % index),
            statement="problem %d" % index,
        ),
        system=System(
            system_id="synthetic",
            name="Synthetic",
            version="1",
            config_hash=hash_json({}),
        ),
        run=Run(
            run_id="oracle",
            environment_hash=hash_json({}),
        ),
        adapter=AdapterInfo(
            name="synthetic",
            version="1",
            fidelity=AdapterFidelity.full,
            source_format="synthetic",
        ),
        sources=sources,
        source_observations=observations,
        evidence=evidence,
        decisions=[],
        provenance_edges=[],
        labels=labels,
        final_output=FinalOutput(
            status=FinalStatus.produced,
            evidence_id="ev:final:%d" % index,
        ),
        audit_only=AuditOnly(gold="1", gold_hash=hash_text("1")),
    )


@pytest.fixture
def episode_factory():
    return build_episode
