# SPDX-License-Identifier: MIT

"""Adapter for MathRouterAgent's Hermes-based staged traces."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..models import (
    AdapterFidelity,
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


class MathRouterAdapter:
    name = "mathrouter"
    version = "0.1.0"

    def can_handle(self, payload: Dict[str, Any]) -> bool:
        steps = [
            str(item.get("step")) for item in payload.get("trace", []) if isinstance(item, dict)
        ]
        return (
            "trace" in payload
            and "validation" not in steps
            and ("reasoning" in steps or any(step.startswith("survival_") for step in steps))
        )

    def convert(
        self,
        payload: Dict[str, Any],
        problem: ProblemContext,
        run: RunContext,
    ) -> Episode:
        trace = [item for item in payload.get("trace", []) if isinstance(item, dict)]
        has_survival = any(str(item.get("step", "")).startswith("survival_") for item in trace)
        base = base_episode_parts(
            problem,
            run,
            adapter_name=self.name,
            adapter_version=self.version,
            fidelity=AdapterFidelity.stage,
            source_format="mathrouter-hermes-staged-json",
            warnings=[
                "Legacy staged trace: selection is observed only when survival_final_selection is present."
            ],
        )
        sources = [
            Source(
                source_id="hermes_reasoner",
                source_type=SourceType.llm,
                role="pass_a",
                producer=run.system_name,
                provenance_group="shared_primary_context",
            ),
            Source(
                source_id="python_executor",
                source_type=SourceType.python,
                role="executable_verifier",
                producer="hermes.execute_code",
                tool="python",
                provenance_group="shared_primary_context",
            ),
            Source(
                source_id="deep_reasoner",
                source_type=SourceType.llm,
                role="pass_b",
                producer=run.system_name,
                provenance_group="shared_model_family",
            ),
            Source(
                source_id="recovery",
                source_type=SourceType.llm,
                role="recovery",
                producer=run.system_name,
                provenance_group="shared_model_family",
            ),
            Source(
                source_id="finalizer",
                source_type=SourceType.composite,
                role="finalizer",
                producer=run.system_name,
                provenance_group="shared_model_family",
            ),
        ]
        observations: List[SourceObservation] = []
        evidence: List[Evidence] = []
        decisions: List[Decision] = []
        edges: List[ProvenanceEdge] = []
        evidence_by_key: Dict[str, str] = {}
        seen = set()
        sequence = 0
        selected_key: Optional[str] = None
        selection_reason: Optional[str] = None
        pass_a_timed_out = False

        for raw in trace:
            step = str(raw.get("step") or "")
            if step == "reasoning":
                text = first_text(raw, "answer") or nested_text(raw, "thinking.final_answer")
                evidence_id = self._record(
                    observations,
                    evidence,
                    source_id="hermes_reasoner",
                    key="A",
                    stage=step,
                    sequence=sequence,
                    text=text,
                    kind=EvidenceKind.candidate_answer,
                    outcome=ObservationOutcome.produced if text else ObservationOutcome.no_vote,
                    metadata={
                        "attempts": raw.get("attempts"),
                        "steps_count": raw.get("steps_count"),
                    },
                )
                seen.add("hermes_reasoner")
                if evidence_id:
                    evidence_by_key["A"] = evidence_id
                sequence += 1
            elif step == "survival_pass_a_timeout":
                pass_a_timed_out = True
            elif step == "survival_pass_a_assess":
                text = first_text(raw, "answer")
                if text:
                    outcome = ObservationOutcome.produced
                elif pass_a_timed_out:
                    outcome = ObservationOutcome.timeout
                else:
                    outcome = ObservationOutcome.no_vote
                evidence_id = self._record(
                    observations,
                    evidence,
                    source_id="hermes_reasoner",
                    key="A",
                    stage=step,
                    sequence=sequence,
                    text=text,
                    kind=EvidenceKind.recovered_answer
                    if pass_a_timed_out
                    else EvidenceKind.candidate_answer,
                    outcome=outcome,
                    metadata={key: value for key, value in raw.items() if key != "step"},
                )
                seen.add("hermes_reasoner")
                if evidence_id:
                    evidence_by_key["A"] = evidence_id
                sequence += 1
            elif step == "python_verification":
                text = first_text(raw, "answer") or nested_text(
                    raw, "thinking.extracted_answer", "thinking.evidence_summary"
                )
                if not text:
                    for tool in raw.get("tools", []) or []:
                        if isinstance(tool, dict):
                            text = first_text(tool, "stdout", "stderr")
                            if text:
                                break
                success = bool(raw.get("success"))
                outcome = (
                    ObservationOutcome.produced
                    if success and text
                    else (ObservationOutcome.no_vote if success else ObservationOutcome.failed)
                )
                evidence_id = self._record(
                    observations,
                    evidence,
                    source_id="python_executor",
                    key="PY",
                    stage=step,
                    sequence=sequence,
                    text=text,
                    kind=EvidenceKind.tool_result,
                    outcome=outcome,
                    metadata={"attempts": raw.get("attempts")},
                )
                seen.add("python_executor")
                if evidence_id:
                    evidence_by_key["PY"] = evidence_id
                    if "A" in evidence_by_key:
                        edges.append(
                            ProvenanceEdge(
                                from_id=evidence_by_key["A"],
                                to_id=evidence_id,
                                relation=EdgeRelation.derived_from,
                                observability=EdgeObservability.declared,
                                metadata={"reason": "tool code generated inside Pass A context"},
                            )
                        )
                sequence += 1
            elif step in {"survival_deep_shot", "survival_deep_shot_exhausted"}:
                text = first_text(raw, "answer")
                detail = str(raw.get("detail") or "")
                if text:
                    outcome = ObservationOutcome.produced
                elif detail == "timeout":
                    outcome = ObservationOutcome.timeout
                elif detail == "failed":
                    outcome = ObservationOutcome.failed
                else:
                    outcome = ObservationOutcome.no_vote
                evidence_id = self._record(
                    observations,
                    evidence,
                    source_id="deep_reasoner",
                    key="B",
                    stage=step,
                    sequence=sequence,
                    text=text,
                    kind=EvidenceKind.candidate_answer,
                    outcome=outcome,
                    metadata={key: value for key, value in raw.items() if key != "step"},
                )
                seen.add("deep_reasoner")
                if evidence_id:
                    evidence_by_key["B"] = evidence_id
                sequence += 1
            elif step in {
                "survival_compressed_retry",
                "survival_compressed_retry_only",
                "survival_emergency_answer",
            }:
                text = first_text(raw, "answer", "guess")
                evidence_id = self._record(
                    observations,
                    evidence,
                    source_id="recovery",
                    key="R",
                    stage=step,
                    sequence=sequence,
                    text=text,
                    kind=EvidenceKind.recovered_answer,
                    outcome=ObservationOutcome.produced if text else ObservationOutcome.no_vote,
                    metadata={key: value for key, value in raw.items() if key != "step"},
                )
                seen.add("recovery")
                if evidence_id:
                    evidence_by_key["B"] = evidence_id
                    evidence_by_key["R"] = evidence_id
                sequence += 1
            elif step == "survival_final_selection":
                selected_key = str(raw.get("winner") or "") or None
                selection_reason = str(raw.get("reason") or "") or None
                candidates = list(
                    dict.fromkeys(
                        value for key, value in evidence_by_key.items() if key in {"A", "B", "R"}
                    )
                )
                selected = (
                    [evidence_by_key[selected_key]] if selected_key in evidence_by_key else []
                )
                decisions.append(
                    Decision(
                        decision_id="decision:final_selection",
                        decision_type=DecisionType.selection,
                        stage=step,
                        sequence=sequence,
                        status=DecisionStatus.completed,
                        input_evidence_ids=candidates,
                        candidate_evidence_ids=candidates,
                        selected_evidence_ids=selected,
                        output_evidence_ids=[],
                        policy=selection_reason or "mathrouter_selection",
                        metadata={"winner_key": selected_key},
                    )
                )
                sequence += 1

        for source_id in ("hermes_reasoner", "python_executor", "deep_reasoner", "recovery"):
            if source_id in seen:
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
        if final_text:
            final_id = self._record(
                observations,
                evidence,
                source_id="finalizer",
                key="F",
                stage="finalization",
                sequence=sequence,
                text=final_text,
                kind=EvidenceKind.final_answer,
                outcome=ObservationOutcome.produced,
                metadata={"legacy_status": payload.get("status")},
            )
            input_ids = list(dict.fromkeys(evidence_by_key.values()))
            selected = []
            if selected_key in evidence_by_key:
                selected = [evidence_by_key[selected_key]]
            decision_id = "decision:finalization"
            decisions.append(
                Decision(
                    decision_id=decision_id,
                    decision_type=DecisionType.finalization,
                    stage="finalization",
                    sequence=sequence,
                    status=DecisionStatus.completed,
                    input_evidence_ids=input_ids,
                    candidate_evidence_ids=input_ids,
                    selected_evidence_ids=selected,
                    output_evidence_ids=[final_id] if final_id else [],
                    policy=selection_reason or "hermes_coordination",
                )
            )
            if final_id:
                edges.append(
                    ProvenanceEdge(
                        from_id=decision_id,
                        to_id=final_id,
                        relation=EdgeRelation.produces,
                        observability=EdgeObservability.observed,
                    )
                )
                for input_id in selected or input_ids:
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
                    observation_id="observation:finalizer",
                    source_id="finalizer",
                    stage="finalization",
                    sequence=sequence,
                    opportunity=Opportunity.eligible,
                    invocation=Invocation.not_observable,
                    outcome=ObservationOutcome.no_vote,
                )
            )
            final_status = FinalStatus.empty

        metadata = {
            "legacy_status": payload.get("status"),
            "has_survival_trace": has_survival,
        }
        diagnostics = next((item for item in trace if item.get("step") == "diagnostics"), None)
        if diagnostics:
            metadata["diagnostics"] = {
                key: value for key, value in diagnostics.items() if key != "step"
            }

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
            metadata=metadata,
        )

    @staticmethod
    def _record(
        observations: List[SourceObservation],
        evidence: List[Evidence],
        *,
        source_id: str,
        key: str,
        stage: str,
        sequence: int,
        text: str,
        kind: EvidenceKind,
        outcome: ObservationOutcome,
        metadata: Dict[str, Any],
    ) -> Optional[str]:
        observation_id = "observation:%s:%d" % (source_id, sequence)
        observations.append(
            SourceObservation(
                observation_id=observation_id,
                source_id=source_id,
                stage=stage,
                sequence=sequence,
                opportunity=Opportunity.eligible,
                invocation=Invocation.called,
                outcome=outcome,
                metadata=metadata,
            )
        )
        if outcome != ObservationOutcome.produced:
            return None
        evidence_id = "evidence:%s:%d" % (key, sequence)
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
