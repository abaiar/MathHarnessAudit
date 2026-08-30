"""Conservative bridge from OTLP JSON GenAI spans to canonical episodes.

OpenTelemetry standardizes execution spans, not mathematical evidence semantics.
The adapter therefore emits evidence only when output content is present and marks
a final answer only through an explicit ``mathaudit.final`` attribute.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ..models import (
    AdapterFidelity,
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


def _otel_value(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    aliases = (
        "stringValue",
        "string_value",
        "intValue",
        "int_value",
        "doubleValue",
        "double_value",
        "boolValue",
        "bool_value",
    )
    for key in aliases:
        if key in value:
            return value[key]
    for key in ("arrayValue", "array_value"):
        if key in value:
            nested = value[key]
            values = nested.get("values", []) if isinstance(nested, dict) else nested
            return [_otel_value(item) for item in values]
    return value


def _attributes(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return {str(key): _otel_value(value) for key, value in raw.items()}
    result: Dict[str, Any] = {}
    for item in raw or []:
        if isinstance(item, dict) and "key" in item:
            result[str(item["key"])] = _otel_value(item.get("value"))
    return result


def _spans(payload: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    resource_spans = payload.get("resourceSpans") or payload.get("resource_spans") or []
    for resource in resource_spans:
        if not isinstance(resource, dict):
            continue
        scope_spans = resource.get("scopeSpans") or resource.get("scope_spans") or []
        for scope in scope_spans:
            if not isinstance(scope, dict):
                continue
            for span in scope.get("spans", []) or []:
                if isinstance(span, dict):
                    yield span


def _content_from_messages(value: Any) -> str:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith(("[", "{")):
            try:
                return _content_from_messages(json.loads(stripped))
            except json.JSONDecodeError:
                return stripped
        return stripped
    if isinstance(value, list):
        parts = [_content_from_messages(item) for item in value]
        return "\n".join(part for part in parts if part).strip()
    if isinstance(value, dict):
        for key in ("text", "content", "message", "output"):
            if key in value:
                text = _content_from_messages(value[key])
                if text:
                    return text
    return ""


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return cleaned[:80] or "unknown"


class OTelAdapter:
    name = "otel"
    version = "0.1.0"

    def can_handle(self, payload: Dict[str, Any]) -> bool:
        return "resourceSpans" in payload or "resource_spans" in payload

    def convert(
        self,
        payload: Dict[str, Any],
        problem: ProblemContext,
        run: RunContext,
    ) -> Episode:
        raw_spans = list(_spans(payload))
        parsed: List[Tuple[Dict[str, Any], Dict[str, Any]]] = [
            (span, _attributes(span.get("attributes"))) for span in raw_spans
        ]
        has_content = any(self._span_text(attributes) for _, attributes in parsed)
        fidelity = AdapterFidelity.stage if has_content else AdapterFidelity.final_only
        base = base_episode_parts(
            problem,
            run,
            adapter_name=self.name,
            adapter_version=self.version,
            fidelity=fidelity,
            source_format="otlp-json-genai",
            warnings=[
                "OTel parent spans describe execution ancestry, not statistical independence.",
                "A final answer is recognized only through mathaudit.final=true.",
            ],
        )
        sources: Dict[str, Source] = {}
        observations: List[SourceObservation] = []
        evidence: List[Evidence] = []
        edges: List[ProvenanceEdge] = []
        evidence_by_span: Dict[str, str] = {}
        final_id: Optional[str] = None

        for sequence, (span, attributes) in enumerate(parsed):
            operation = str(attributes.get("gen_ai.operation.name") or span.get("name") or "operation")
            tool_name = attributes.get("gen_ai.tool.name")
            model_name = attributes.get("gen_ai.request.model") or attributes.get("gen_ai.response.model")
            agent_name = attributes.get("gen_ai.agent.name") or attributes.get("gen_ai.workflow.name")
            if tool_name or operation == "execute_tool":
                source_type = SourceType.other
                role = "tool"
                stable_name = str(tool_name or operation)
            else:
                source_type = SourceType.llm
                role = "agent_or_model"
                stable_name = str(agent_name or model_name or operation)
            source_id = "otel:%s:%s" % (role, _slug(stable_name))
            sources.setdefault(
                source_id,
                Source(
                    source_id=source_id,
                    source_type=source_type,
                    role=role,
                    producer=str(agent_name) if agent_name else None,
                    model=str(model_name) if model_name else None,
                    tool=str(tool_name) if tool_name else None,
                    provenance_group="otel_trace:%s" % (span.get("traceId") or span.get("trace_id") or run.run_id),
                ),
            )
            span_id = str(span.get("spanId") or span.get("span_id") or sequence)
            observation_id = "observation:otel:%s" % span_id
            text = self._span_text(attributes)
            status = span.get("status") or {}
            status_code = str(status.get("code") or status.get("statusCode") or "").upper() if isinstance(status, dict) else str(status).upper()
            if "ERROR" in status_code or attributes.get("error.type"):
                outcome = ObservationOutcome.failed
            elif text:
                outcome = ObservationOutcome.produced
            else:
                outcome = ObservationOutcome.no_vote
            observations.append(
                SourceObservation(
                    observation_id=observation_id,
                    source_id=source_id,
                    stage=operation,
                    sequence=sequence,
                    opportunity=Opportunity.eligible,
                    invocation=Invocation.called,
                    outcome=outcome,
                    metadata={"span_id": span_id, "span_name": span.get("name")},
                )
            )
            if outcome != ObservationOutcome.produced:
                continue
            explicit_final = self._truthy(attributes.get("mathaudit.final"))
            if explicit_final:
                kind = EvidenceKind.final_answer
            elif tool_name or operation == "execute_tool":
                kind = EvidenceKind.tool_result
            else:
                kind = EvidenceKind.candidate_answer
            evidence_id = "evidence:otel:%s" % span_id
            evidence.append(
                Evidence(
                    evidence_id=evidence_id,
                    observation_id=observation_id,
                    kind=kind,
                    stage=operation,
                    sequence=sequence,
                    content=make_content(text),
                    metadata={"span_id": span_id},
                )
            )
            evidence_by_span[span_id] = evidence_id
            if explicit_final:
                final_id = evidence_id

        for span, _ in parsed:
            span_id = str(span.get("spanId") or span.get("span_id") or "")
            parent_id = str(span.get("parentSpanId") or span.get("parent_span_id") or "")
            if span_id in evidence_by_span and parent_id in evidence_by_span:
                edges.append(
                    ProvenanceEdge(
                        from_id=evidence_by_span[parent_id],
                        to_id=evidence_by_span[span_id],
                        relation=EdgeRelation.derived_from,
                        observability=EdgeObservability.adapter_inferred,
                        metadata={"basis": "OTel parentSpanId"},
                    )
                )

        final_status = FinalStatus.produced if final_id else FinalStatus.empty
        return Episode(
            episode_id="%s:%s:%s" % (run.run_id, run.system_id, problem.problem_id),
            problem=base[0],
            system=base[1],
            run=base[2],
            adapter=base[3],
            sources=list(sources.values()),
            source_observations=observations,
            evidence=evidence,
            decisions=[],
            provenance_edges=edges,
            labels=[],
            final_output=FinalOutput(status=final_status, evidence_id=final_id),
            audit_only=base[4],
            metadata={"otel_span_count": len(raw_spans)},
        )

    @staticmethod
    def _span_text(attributes: Dict[str, Any]) -> str:
        for key in (
            "mathaudit.evidence.text",
            "gen_ai.output.messages",
            "gen_ai.response.text",
            "output.value",
        ):
            if key in attributes:
                text = _content_from_messages(attributes[key])
                if text:
                    return text
        return ""

    @staticmethod
    def _truthy(value: Any) -> bool:
        return value is True or str(value).strip().lower() in {"1", "true", "yes"}
