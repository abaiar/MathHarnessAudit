"""Adapters for full MathGoal artifacts and compact regression outputs."""

from __future__ import annotations

import re
from collections import Counter
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
from .common import base_episode_parts, make_content


class MathGoalAdapter:
    name = "mathgoal"
    version = "0.2.0"

    def can_handle(self, payload: Dict[str, Any]) -> bool:
        compact = (
            {"id", "pred", "llm_calls"}.issubset(payload)
            or {"idx", "prediction", "api_calls"}.issubset(payload)
        )
        full = {"problem_id", "answer", "candidates", "verifications"}.issubset(payload)
        return compact or full

    def convert(
        self,
        payload: Dict[str, Any],
        problem: ProblemContext,
        run: RunContext,
    ) -> Episode:
        if "candidates" in payload and "verifications" in payload:
            return self._convert_full(payload, problem, run)
        return self._convert_compact(payload, problem, run)

    def _convert_compact(self, payload: Dict[str, Any], problem: ProblemContext, run: RunContext) -> Episode:
        base = base_episode_parts(
            problem,
            run,
            adapter_name=self.name,
            adapter_version=self.version,
            fidelity=AdapterFidelity.final_only,
            source_format="mathgoal-regression-jsonl",
            warnings=["Compact MathGoal output exposes only the final prediction and aggregate cost."],
        )
        source = Source(
            source_id="mathgoal_final",
            source_type=SourceType.composite,
            role="orchestrated_final",
            producer="MathGoal",
            provenance_group="mathgoal_orchestrator",
        )
        text = str(payload.get("pred") or payload.get("prediction") or "").strip()
        error = str(payload.get("error") or "").strip()
        if text:
            outcome = ObservationOutcome.produced
        elif error:
            outcome = ObservationOutcome.failed
        else:
            outcome = ObservationOutcome.no_vote
        observation = SourceObservation(
            observation_id="observation:mathgoal_final",
            source_id=source.source_id,
            stage="final",
            opportunity=Opportunity.eligible,
            invocation=Invocation.called,
            outcome=outcome,
            cost=Cost(
                calls=self._int_or_none(payload.get("llm_calls") if payload.get("llm_calls") is not None else payload.get("api_calls")),
                prompt_tokens=self._int_or_none(payload.get("prompt_tokens")),
                completion_tokens=self._int_or_none(payload.get("completion_tokens")),
                total_tokens=self._int_or_none(
                    payload.get("total_tokens")
                    if payload.get("total_tokens") is not None
                    else self._sum_tokens(payload)
                ),
                latency_s=self._float_or_none(
                    payload.get("elapsed_seconds")
                    if payload.get("elapsed_seconds") is not None
                    else payload.get("wall_seconds")
                ),
            ),
            metadata={"error": error or None},
        )
        evidence: List[Evidence] = []
        final_id: Optional[str] = None
        final_status = FinalStatus.empty
        if outcome == ObservationOutcome.produced:
            final_id = "evidence:final"
            evidence.append(
                Evidence(
                    evidence_id=final_id,
                    observation_id=observation.observation_id,
                    kind=EvidenceKind.final_answer,
                    stage="final",
                    sequence=0,
                    content=make_content(text),
                )
            )
            final_status = FinalStatus.produced
        elif outcome == ObservationOutcome.failed:
            final_status = FinalStatus.failed

        audit_only = base[4]
        audit_only.metadata.update(
            {
                "legacy_correct": payload.get("correct"),
                "legacy_gold_present": "gold" in payload,
            }
        )
        return Episode(
            episode_id="%s:%s:%s" % (run.run_id, run.system_id, problem.problem_id),
            problem=base[0],
            system=base[1],
            run=base[2],
            adapter=base[3],
            sources=[source],
            source_observations=[observation],
            evidence=evidence,
            decisions=[],
            provenance_edges=[],
            labels=[],
            final_output=FinalOutput(status=final_status, evidence_id=final_id),
            audit_only=audit_only,
            metadata={
                "auto_route": payload.get("auto_route"),
                "budget_profile": payload.get("budget_profile"),
                "needs_review": payload.get("needs_review"),
            },
        )

    def _convert_full(self, payload: Dict[str, Any], problem: ProblemContext, run: RunContext) -> Episode:
        base = base_episode_parts(
            problem,
            run,
            adapter_name=self.name,
            adapter_version=self.version,
            fidelity=AdapterFidelity.full,
            source_format="mathgoal-solve-result-json",
        )
        sources: List[Source] = []
        observations: List[SourceObservation] = []
        evidence: List[Evidence] = []
        decisions: List[Decision] = []
        edges: List[ProvenanceEdge] = []
        candidate_ids: Dict[str, str] = {}
        candidate_source_ids: Dict[str, str] = {}
        tool_evidence_ids: Dict[str, str] = {}
        corrected_candidates: List[tuple[str, str]] = []
        role_counts: Counter[str] = Counter()
        sequence = 0

        for candidate in payload.get("candidates", []) or []:
            if not isinstance(candidate, dict):
                continue
            candidate_key = str(candidate.get("id") or "candidate_%d" % sequence)
            raw_role = str(candidate.get("agent_role") or "solver")
            original_key = (
                candidate_key[: -len("_tool")]
                if raw_role == "tool_corrected" and candidate_key.endswith("_tool")
                else candidate_key
            )
            role_key = re.sub(r"[^a-z0-9_]+", "_", raw_role.lower()).strip("_") or "solver"
            if raw_role == "tool_corrected" and original_key in candidate_source_ids:
                original_role_key = candidate_source_ids[original_key].split(":", 1)[1]
                role_key = "%s:tool_corrected" % original_role_key
            role_counts[role_key] += 1
            role_suffix = "" if role_counts[role_key] == 1 else ":%d" % role_counts[role_key]
            source_id = "candidate_role:%s%s" % (role_key, role_suffix)
            provenance_key = original_key if raw_role == "tool_corrected" else candidate_key
            candidate_source_ids[candidate_key] = source_id
            sources.append(
                Source(
                    source_id=source_id,
                    source_type=SourceType.llm,
                    role=raw_role,
                    producer="MathGoal",
                    provenance_group="mathgoal_candidate:%s" % provenance_key,
                    metadata={"candidate_id": candidate_key},
                )
            )
            text = str(candidate.get("answer") or "").strip()
            observation_id = "observation:%s" % source_id
            outcome = ObservationOutcome.produced if text else ObservationOutcome.no_vote
            observations.append(SourceObservation(observation_id=observation_id, source_id=source_id, stage="candidate", sequence=sequence, opportunity=Opportunity.eligible, invocation=Invocation.called, outcome=outcome))
            if text:
                evidence_id = "evidence:%s" % source_id
                candidate_ids[candidate_key] = evidence_id
                evidence.append(Evidence(evidence_id=evidence_id, observation_id=observation_id, kind=EvidenceKind.candidate_answer, stage="candidate", sequence=sequence, content=make_content(text), metadata={"confidence": candidate.get("confidence"), "candidate_id": candidate_key, "agent_role": raw_role}))
            sequence += 1

            tool_report = candidate.get("tool_report")
            if raw_role != "tool_corrected":
                tool_source = "tool_role:%s%s" % (role_key, role_suffix)
                sources.append(Source(source_id=tool_source, source_type=SourceType.python, role="candidate_tool", producer="MathGoal", tool="python/sympy", provenance_group="mathgoal_candidate:%s" % candidate_key, metadata={"candidate_id": candidate_key, "candidate_role": raw_role}))
                tool_observation = "observation:%s" % tool_source
                if isinstance(tool_report, dict):
                    tool_text = str(tool_report.get("extracted_answer") or tool_report.get("stdout") or tool_report.get("stderr") or "").strip()
                    ok = bool(tool_report.get("ok"))
                    if ok and tool_text:
                        tool_outcome = ObservationOutcome.produced
                    elif ok:
                        tool_outcome = ObservationOutcome.no_vote
                    elif tool_report.get("timed_out"):
                        tool_outcome = ObservationOutcome.timeout
                    else:
                        tool_outcome = ObservationOutcome.failed
                    observations.append(SourceObservation(observation_id=tool_observation, source_id=tool_source, stage="tool", sequence=sequence, opportunity=Opportunity.eligible, invocation=Invocation.called, outcome=tool_outcome, cost=Cost(latency_s=self._float_or_none(tool_report.get("elapsed_seconds")), tool_executions=1), metadata={key: tool_report.get(key) for key in ("blocked", "timed_out", "independent_work", "evidence_score", "tool_conflict")}))
                    if tool_outcome == ObservationOutcome.produced:
                        tool_id = "evidence:%s" % tool_source
                        tool_evidence_ids[candidate_key] = tool_id
                        evidence.append(Evidence(evidence_id=tool_id, observation_id=tool_observation, kind=EvidenceKind.tool_result, stage="tool", sequence=sequence, content=make_content(tool_text), metadata={"evidence_flags": tool_report.get("evidence_flags", [])}))
                        if candidate_key in candidate_ids:
                            edges.append(ProvenanceEdge(from_id=candidate_ids[candidate_key], to_id=tool_id, relation=EdgeRelation.derived_from, observability=EdgeObservability.adapter_inferred))
                else:
                    observations.append(SourceObservation(observation_id=tool_observation, source_id=tool_source, stage="tool", sequence=sequence, opportunity=Opportunity.unknown, invocation=Invocation.not_called, outcome=ObservationOutcome.not_observable))
                sequence += 1
            if raw_role == "tool_corrected" and original_key != candidate_key:
                corrected_candidates.append((candidate_key, original_key))

        for corrected_key, original_key in corrected_candidates:
            corrected_id = candidate_ids.get(corrected_key)
            if corrected_id is None:
                continue
            if original_key in candidate_ids:
                edges.append(ProvenanceEdge(from_id=candidate_ids[original_key], to_id=corrected_id, relation=EdgeRelation.derived_from, observability=EdgeObservability.adapter_inferred))
            if original_key in tool_evidence_ids:
                edges.append(ProvenanceEdge(from_id=tool_evidence_ids[original_key], to_id=corrected_id, relation=EdgeRelation.derived_from, observability=EdgeObservability.adapter_inferred))

        verifier_source = Source(source_id="mathgoal_verifier", source_type=SourceType.llm, role="verifier", producer="MathGoal", provenance_group="mathgoal_verifier")
        sources.append(verifier_source)
        verification_reports = payload.get("verifications", []) or []
        if not verification_reports:
            observations.append(SourceObservation(observation_id="observation:verifier:0", source_id=verifier_source.source_id, stage="verification", sequence=sequence, opportunity=Opportunity.unknown, invocation=Invocation.not_called, outcome=ObservationOutcome.not_observable))
            sequence += 1
        for index, report in enumerate(verification_reports):
            if not isinstance(report, dict):
                continue
            candidate_key = str(report.get("candidate_id") or "")
            text = str(report.get("normalized_answer") or "").strip()
            if not text:
                issues = report.get("issues") or []
                text = "\n".join(str(item) for item in issues)
            observation_id = "observation:verifier:%d" % index
            outcome = ObservationOutcome.produced if text else ObservationOutcome.no_vote
            observations.append(SourceObservation(observation_id=observation_id, source_id=verifier_source.source_id, stage="verification", sequence=sequence, opportunity=Opportunity.eligible, invocation=Invocation.called, outcome=outcome))
            output_ids: List[str] = []
            if text:
                evidence_id = "evidence:verifier:%d" % index
                evidence.append(Evidence(evidence_id=evidence_id, observation_id=observation_id, kind=EvidenceKind.verifier_verdict, stage="verification", sequence=sequence, content=make_content(text), metadata={"is_correct": report.get("is_correct"), "score": report.get("score"), "fix_hint": report.get("fix_hint")}))
                output_ids.append(evidence_id)
                if candidate_key in candidate_ids:
                    edges.append(ProvenanceEdge(from_id=candidate_ids[candidate_key], to_id=evidence_id, relation=EdgeRelation.derived_from, observability=EdgeObservability.observed))
            input_ids = [candidate_ids[candidate_key]] if candidate_key in candidate_ids else []
            decision_id = "decision:verification:%d" % index
            decisions.append(Decision(decision_id=decision_id, decision_type=DecisionType.validation, stage="verification", sequence=sequence, status=DecisionStatus.completed if output_ids else DecisionStatus.not_observable, input_evidence_ids=input_ids, candidate_evidence_ids=input_ids, selected_evidence_ids=[], output_evidence_ids=output_ids, policy="mathgoal_verifier"))
            for output_id in output_ids:
                edges.append(ProvenanceEdge(from_id=decision_id, to_id=output_id, relation=EdgeRelation.produces, observability=EdgeObservability.observed))
            sequence += 1

        final_source = Source(source_id="mathgoal_final", source_type=SourceType.composite, role="orchestrated_final", producer="MathGoal", provenance_group="mathgoal_orchestrator")
        sources.append(final_source)
        final_text = str(payload.get("answer") or "").strip()
        final_observation = "observation:mathgoal_final"
        final_outcome = ObservationOutcome.produced if final_text else ObservationOutcome.no_vote
        observations.append(SourceObservation(observation_id=final_observation, source_id=final_source.source_id, stage="final", sequence=sequence, opportunity=Opportunity.eligible, invocation=Invocation.called, outcome=final_outcome))
        final_id: Optional[str] = None
        if final_text:
            final_id = "evidence:final"
            evidence.append(Evidence(evidence_id=final_id, observation_id=final_observation, kind=EvidenceKind.final_answer, stage="final", sequence=sequence, content=make_content(final_text)))
            inputs = [item.evidence_id for item in evidence if item.evidence_id != final_id]
            decision_id = "decision:finalization"
            decisions.append(Decision(decision_id=decision_id, decision_type=DecisionType.finalization, stage="final", sequence=sequence, status=DecisionStatus.completed, input_evidence_ids=inputs, candidate_evidence_ids=list(candidate_ids.values()), selected_evidence_ids=[], output_evidence_ids=[final_id], policy="mathgoal_cluster_scoring"))
            edges.append(ProvenanceEdge(from_id=decision_id, to_id=final_id, relation=EdgeRelation.produces, observability=EdgeObservability.observed))

        return Episode(
            episode_id="%s:%s:%s" % (run.run_id, run.system_id, problem.problem_id),
            problem=base[0], system=base[1], run=base[2], adapter=base[3],
            sources=sources, source_observations=observations, evidence=evidence,
            decisions=decisions, provenance_edges=edges, labels=[],
            final_output=FinalOutput(status=FinalStatus.produced if final_id else FinalStatus.empty, evidence_id=final_id),
            audit_only=base[4],
            metadata={"classification": payload.get("classification"), "plan": payload.get("plan"), "mathgoal_metadata": payload.get("metadata")},
        )

    @staticmethod
    def _int_or_none(value: Any) -> Optional[int]:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _float_or_none(value: Any) -> Optional[float]:
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @classmethod
    def _sum_tokens(cls, payload: Dict[str, Any]) -> Optional[int]:
        prompt = cls._int_or_none(payload.get("prompt_tokens"))
        completion = cls._int_or_none(payload.get("completion_tokens"))
        if prompt is None and completion is None:
            return None
        return (prompt or 0) + (completion or 0)
