# SPDX-License-Identifier: MIT

"""Adapter for legacy ICMA staged JSON traces."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..models import (
    AdapterFidelity,
    Cost,
    Decision,
    DecisionStatus,
    DecisionType,
    EdgeObservability,
    EdgeRelation,
    Episode,
    Evidence,
    EvidenceKind,
    FinalOutput,
    FinalStatus,
    Invocation,
    ObservationOutcome,
    Opportunity,
    ProvenanceEdge,
    Source,
    SourceObservation,
    SourceType,
)
from .base import ProblemContext, RunContext
from .common import base_episode_parts, first_text, make_content, nested_text


class ICMAAdapter:
    name = "icma"
    version = "0.1.0"

    _source_specs = {
        "reasoner": (SourceType.llm, "primary_reasoner"),
        "python_executor": (SourceType.python, "executable_verifier"),
        "validator": (SourceType.llm, "validator"),
        "coordinator": (SourceType.composite, "coordinator"),
    }

    def can_handle(self, payload: Dict[str, Any]) -> bool:
        steps = {str(item.get("step")) for item in payload.get("trace", []) if isinstance(item, dict)}
        return "validation" in steps and "reasoning" in steps and "trace" in payload

    def convert(
        self,
        payload: Dict[str, Any],
        problem: ProblemContext,
        run: RunContext,
    ) -> Episode:
        warnings = [
            "Legacy ICMA trace: evidence parentage and per-stage cost are partially unobservable."
        ]
        base = base_episode_parts(
            problem,
            run,
            adapter_name=self.name,
            adapter_version=self.version,
            fidelity=AdapterFidelity.stage,
            source_format="icma-staged-json",
            warnings=warnings,
        )
        sources = [
            Source(
                source_id=source_id,
                source_type=spec[0],
                role=spec[1],
                producer=run.system_name,
                provenance_group="shared_episode_context",
            )
            for source_id, spec in self._source_specs.items()
        ]
        observations: List[SourceObservation] = []
        evidence: List[Evidence] = []
        decisions: List[Decision] = []
        edges: List[ProvenanceEdge] = []
        seen_sources = set()
        stage_evidence: Dict[str, str] = {}
        episode_metadata: Dict[str, Any] = {"legacy_status": payload.get("status")}
        sequence = 0

        for raw in payload.get("trace", []):
            if not isinstance(raw, dict):
                continue
            step = str(raw.get("step") or "")
            if step == "classification":
                episode_metadata["classification"] = {
                    key: raw.get(key)
                    for key in ("category", "question_mode", "confidence", "candidates")
                    if key in raw
                }
                continue
            if step == "reasoning":
                answer = first_text(raw, "answer") or nested_text(raw, "thinking.final_answer")
                evidence_id = self._add_stage_evidence(
                    observations,
                    evidence,
                    seen_sources,
                    source_id="reasoner",
                    stage=step,
                    sequence=sequence,
                    text=answer,
                    success=True,
                    kind=EvidenceKind.candidate_answer,
                    metadata={"attempts": raw.get("attempts"), "steps_count": raw.get("steps_count")},
                )
                if evidence_id:
                    stage_evidence[step] = evidence_id
                sequence += 1
                continue
            if step == "python_verification":
                tool_text = first_text(raw, "answer") or nested_text(
                    raw,
                    "thinking.extracted_answer",
                    "thinking.evidence_summary",
                )
                if not tool_text:
                    for tool in raw.get("tools", []) or []:
                        if isinstance(tool, dict):
                            tool_text = first_text(tool, "stdout", "stderr")
                            if tool_text:
                                break
                evidence_id = self._add_stage_evidence(
                    observations,
                    evidence,
                    seen_sources,
                    source_id="python_executor",
                    stage=step,
                    sequence=sequence,
                    text=tool_text,
                    success=bool(raw.get("success")),
                    kind=EvidenceKind.tool_result,
                    metadata={"attempts": raw.get("attempts")},
                )
                if evidence_id:
                    stage_evidence[step] = evidence_id
                sequence += 1
                continue
            if step == "validation":
                text = first_text(raw, "validated_answer")
                evidence_id = self._add_stage_evidence(
                    observations,
                    evidence,
                    seen_sources,
                    source_id="validator",
                    stage=step,
                    sequence=sequence,
                    text=text,
                    success=str(raw.get("status") or "").lower() not in {"failed", "timeout"},
                    kind=EvidenceKind.verifier_verdict,
                    metadata={"legacy_validation_status": raw.get("status")},
                )
                inputs = [
                    stage_evidence[name]
                    for name in ("reasoning", "python_verification")
                    if name in stage_evidence
                ]
                outputs = [evidence_id] if evidence_id else []
                decision_id = "decision:validation"
                decisions.append(
                    Decision(
                        decision_id=decision_id,
                        decision_type=DecisionType.validation,
                        stage=step,
                        sequence=sequence,
                        status=DecisionStatus.completed if evidence_id else DecisionStatus.not_observable,
                        input_evidence_ids=inputs,
                        candidate_evidence_ids=inputs,
                        selected_evidence_ids=[],
                        output_evidence_ids=outputs,
                        policy="icma_validation",
                        metadata={"legacy_status": raw.get("status")},
                    )
                )
                if evidence_id:
                    stage_evidence[step] = evidence_id
                    edges.append(
                        ProvenanceEdge(
                            from_id=decision_id,
                            to_id=evidence_id,
                            relation=EdgeRelation.produces,
                            observability=EdgeObservability.observed,
                        )
                    )
                    for input_id in inputs:
                        edges.append(
                            ProvenanceEdge(
                                from_id=input_id,
                                to_id=evidence_id,
                                relation=EdgeRelation.derived_from,
                                observability=EdgeObservability.adapter_inferred,
                            )
                        )
                sequence += 1
                continue
            if step == "semantic_arbitration":
                candidates = list(stage_evidence.values())
                status_raw = str(raw.get("status") or "").lower()
                status = DecisionStatus.skipped if status_raw == "skipped" else DecisionStatus.completed
                decisions.append(
                    Decision(
                        decision_id="decision:semantic_arbitration",
                        decision_type=DecisionType.arbitration,
                        stage=step,
                        sequence=sequence,
                        status=status,
                        input_evidence_ids=candidates,
                        candidate_evidence_ids=candidates,
                        selected_evidence_ids=[],
                        output_evidence_ids=[],
                        policy="icma_semantic_arbitration",
                        metadata={
                            "legacy_status": raw.get("status"),
                            "legacy_decision": raw.get("decision"),
                            "answer_locked": raw.get("answer_locked"),
                        },
                    )
                )
                sequence += 1

        for source_id in self._source_specs:
            if source_id == "coordinator" or source_id in seen_sources:
                continue
            observations.append(
                SourceObservation(
                    observation_id="observation:%s" % source_id,
                    source_id=source_id,
                    stage="unobserved",
                    sequence=sequence,
                    opportunity=Opportunity.unknown,
                    invocation=Invocation.not_observable,
                    outcome=ObservationOutcome.not_observable,
                )
            )
            sequence += 1

        final_text = str(payload.get("final_response") or "").strip()
        final_id: Optional[str] = None
        final_status = FinalStatus.empty
        if final_text:
            observation_id = "observation:coordinator"
            observations.append(
                SourceObservation(
                    observation_id=observation_id,
                    source_id="coordinator",
                    stage="coordination",
                    sequence=sequence,
                    opportunity=Opportunity.eligible,
                    invocation=Invocation.called,
                    outcome=ObservationOutcome.produced,
                )
            )
            final_id = "evidence:final"
            evidence.append(
                Evidence(
                    evidence_id=final_id,
                    observation_id=observation_id,
                    kind=EvidenceKind.final_answer,
                    stage="coordination",
                    sequence=sequence,
                    content=make_content(final_text),
                )
            )
            inputs = list(stage_evidence.values())
            decision_id = "decision:finalization"
            decisions.append(
                Decision(
                    decision_id=decision_id,
                    decision_type=DecisionType.finalization,
                    stage="coordination",
                    sequence=sequence,
                    status=DecisionStatus.completed,
                    input_evidence_ids=inputs,
                    candidate_evidence_ids=inputs,
                    selected_evidence_ids=[],
                    output_evidence_ids=[final_id],
                    policy="icma_coordinator",
                )
            )
            edges.append(
                ProvenanceEdge(
                    from_id=decision_id,
                    to_id=final_id,
                    relation=EdgeRelation.produces,
                    observability=EdgeObservability.observed,
                )
            )
            for input_id in inputs:
                edges.append(
                    ProvenanceEdge(
                        from_id=input_id,
                        to_id=final_id,
                        relation=EdgeRelation.aggregates,
                        observability=EdgeObservability.adapter_inferred,
                    )
                )
            final_status = FinalStatus.produced
        else:
            observations.append(
                SourceObservation(
                    observation_id="observation:coordinator",
                    source_id="coordinator",
                    stage="coordination",
                    sequence=sequence,
                    opportunity=Opportunity.eligible,
                    invocation=Invocation.not_observable,
                    outcome=ObservationOutcome.no_vote,
                )
            )

        return Episode(
            episode_id="%s:%s:%s" % (run.run_id, run.system_id, problem.problem_id),
            problem=base[0],
            system=base[1],
            run=base[2],
            adapter=base[3],
            sources=sources,
            source_observations=observations,
            evidence=evidence,
            decisions=decisions,
            provenance_edges=edges,
            labels=[],
            final_output=FinalOutput(status=final_status, evidence_id=final_id),
            audit_only=base[4],
            metadata=episode_metadata,
        )

    @staticmethod
    def _add_stage_evidence(
        observations: List[SourceObservation],
        evidence: List[Evidence],
        seen_sources: set,
        *,
        source_id: str,
        stage: str,
        sequence: int,
        text: str,
        success: bool,
        kind: EvidenceKind,
        metadata: Dict[str, Any],
    ) -> Optional[str]:
        observation_id = "observation:%s" % source_id
        seen_sources.add(source_id)
        if success and text:
            outcome = ObservationOutcome.produced
        elif success:
            outcome = ObservationOutcome.no_vote
        else:
            outcome = ObservationOutcome.failed
        observations.append(
            SourceObservation(
                observation_id=observation_id,
                source_id=source_id,
                stage=stage,
                sequence=sequence,
                opportunity=Opportunity.eligible,
                invocation=Invocation.called,
                outcome=outcome,
                cost=Cost(calls=1),
                metadata=metadata,
            )
        )
        if outcome != ObservationOutcome.produced:
            return None
        evidence_id = "evidence:%s" % source_id
        evidence.append(
            Evidence(
                evidence_id=evidence_id,
                observation_id=observation_id,
                kind=kind,
                stage=stage,
                sequence=sequence,
                content=make_content(text),
                metadata=metadata,
            )
        )
        return evidence_id
