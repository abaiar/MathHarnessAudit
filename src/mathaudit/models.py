# SPDX-License-Identifier: MIT

"""Canonical outcome-linked evidence models.

The Pydantic models enforce JSON-level structure. Cross-reference and graph
invariants are checked separately by :mod:`mathaudit.validation` so callers can
inspect all semantic issues in one pass.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HashValue(StrictModel):
    algorithm: str = Field(default="sha256", pattern="^sha256$")
    value: str = Field(pattern=r"^[A-Fa-f0-9]{64}$")


class Money(StrictModel):
    amount: float = Field(ge=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")


class Cost(StrictModel):
    calls: Optional[int] = Field(default=None, ge=0)
    prompt_tokens: Optional[int] = Field(default=None, ge=0)
    completion_tokens: Optional[int] = Field(default=None, ge=0)
    total_tokens: Optional[int] = Field(default=None, ge=0)
    tool_executions: Optional[int] = Field(default=None, ge=0)
    latency_s: Optional[float] = Field(default=None, ge=0)
    monetary: Optional[Money] = None


class Problem(StrictModel):
    problem_id: str = Field(min_length=1)
    dataset_id: str = Field(min_length=1)
    dataset_version: Optional[str] = None
    split: str = Field(min_length=1)
    stratum: str = Field(min_length=1)
    domain: Optional[str] = None
    difficulty: Optional[str] = None
    answer_type: Optional[str] = None
    input_hash: HashValue
    statement: Optional[str] = None
    solver_visible_metadata: Dict[str, Any] = Field(default_factory=dict)


class System(StrictModel):
    system_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    harness_family: Optional[str] = None
    repository: Optional[str] = None
    commit: Optional[str] = None
    config_hash: HashValue


class Run(StrictModel):
    run_id: str = Field(min_length=1)
    seed: Optional[int] = None
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    budget: Dict[str, Any] = Field(default_factory=dict)
    environment_hash: HashValue
    provider_request_ids: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def timestamps_are_ordered(self) -> "Run":
        if self.started_at and self.ended_at and self.ended_at < self.started_at:
            raise ValueError("run.ended_at precedes run.started_at")
        return self


class AdapterFidelity(str, Enum):
    full = "A"
    stage = "B"
    final_only = "C"


class AdapterInfo(StrictModel):
    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    fidelity: AdapterFidelity
    source_format: str = Field(min_length=1)
    warnings: List[str] = Field(default_factory=list)


class SourceType(str, Enum):
    llm = "llm"
    python = "python"
    sympy = "sympy"
    formal = "formal"
    human = "human"
    deterministic = "deterministic"
    composite = "composite"
    other = "other"


class Source(StrictModel):
    source_id: str = Field(min_length=1)
    source_type: SourceType
    role: str = Field(min_length=1)
    producer: Optional[str] = None
    model: Optional[str] = None
    tool: Optional[str] = None
    provenance_group: str = Field(min_length=1)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class Opportunity(str, Enum):
    eligible = "eligible"
    ineligible = "ineligible"
    unknown = "unknown"


class Invocation(str, Enum):
    called = "called"
    not_called = "not_called"
    not_observable = "not_observable"


class ObservationOutcome(str, Enum):
    produced = "produced"
    no_vote = "no_vote"
    failed = "failed"
    timeout = "timeout"
    cancelled = "cancelled"
    not_observable = "not_observable"


class SourceObservation(StrictModel):
    observation_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    stage: str = Field(min_length=1)
    sequence: int = Field(default=0, ge=0)
    opportunity: Opportunity
    invocation: Invocation
    outcome: ObservationOutcome
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    cost: Cost = Field(default_factory=Cost)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def observation_is_temporally_valid(self) -> "SourceObservation":
        if self.started_at and self.ended_at and self.ended_at < self.started_at:
            raise ValueError("source observation ended before it started")
        return self


class Visibility(str, Enum):
    public = "public"
    private = "private"
    redacted = "redacted"
    hash_only = "hash_only"


class EvidenceContent(StrictModel):
    visibility: Visibility
    text: Optional[str] = None
    content_hash: HashValue
    normalized_answer: Optional[str] = None
    structured: Any = None


class EvidenceKind(str, Enum):
    candidate_answer = "candidate_answer"
    reasoning_claim = "reasoning_claim"
    tool_result = "tool_result"
    verifier_verdict = "verifier_verdict"
    critique = "critique"
    recovered_answer = "recovered_answer"
    final_answer = "final_answer"
    other = "other"


class Evidence(StrictModel):
    evidence_id: str = Field(min_length=1)
    observation_id: str = Field(min_length=1)
    kind: EvidenceKind
    stage: str = Field(min_length=1)
    sequence: int = Field(ge=0)
    created_at: Optional[datetime] = None
    content: EvidenceContent
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DecisionType(str, Enum):
    validation = "validation"
    arbitration = "arbitration"
    selection = "selection"
    repair = "repair"
    recovery = "recovery"
    finalization = "finalization"
    other = "other"


class DecisionStatus(str, Enum):
    completed = "completed"
    skipped = "skipped"
    failed = "failed"
    timeout = "timeout"
    not_observable = "not_observable"


class Decision(StrictModel):
    decision_id: str = Field(min_length=1)
    decision_type: DecisionType
    stage: str = Field(min_length=1)
    sequence: int = Field(ge=0)
    status: DecisionStatus
    input_evidence_ids: List[str] = Field(default_factory=list)
    candidate_evidence_ids: List[str] = Field(default_factory=list)
    selected_evidence_ids: List[str] = Field(default_factory=list)
    output_evidence_ids: List[str] = Field(default_factory=list)
    policy: str = Field(min_length=1)
    created_at: Optional[datetime] = None
    cost: Cost = Field(default_factory=Cost)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class EdgeRelation(str, Enum):
    derived_from = "derived_from"
    verifies = "verifies"
    critiques = "critiques"
    supports = "supports"
    contradicts = "contradicts"
    aggregates = "aggregates"
    produces = "produces"


class EdgeObservability(str, Enum):
    observed = "observed"
    adapter_inferred = "adapter_inferred"
    declared = "declared"


class ProvenanceEdge(StrictModel):
    from_id: str = Field(min_length=1)
    to_id: str = Field(min_length=1)
    relation: EdgeRelation
    observability: EdgeObservability
    metadata: Dict[str, Any] = Field(default_factory=dict)


class LabelValue(str, Enum):
    correct = "correct"
    incorrect = "incorrect"
    abstain = "abstain"
    unscorable = "unscorable"


class ScorerType(str, Enum):
    exact = "exact"
    numeric = "numeric"
    symbolic = "symbolic"
    executable = "executable"
    formal = "formal"
    llm = "llm"
    human = "human"
    adjudicated = "adjudicated"


class AdjudicationStatus(str, Enum):
    not_needed = "not_needed"
    pending = "pending"
    resolved = "resolved"
    unresolved = "unresolved"


class OutcomeLabel(StrictModel):
    label_id: str = Field(min_length=1)
    target_type: str = Field(pattern=r"^(episode|evidence)$")
    target_id: str = Field(min_length=1)
    value: LabelValue
    scorer_type: ScorerType
    scorer_name: str = Field(min_length=1)
    scorer_version: str = Field(min_length=1)
    rule_id: Optional[str] = None
    decision_path: List[str] = Field(default_factory=list)
    confidence: Optional[float] = Field(default=None, ge=0, le=1)
    adjudication_status: AdjudicationStatus
    annotator_id: Optional[str] = None
    created_at: datetime
    metadata: Dict[str, Any] = Field(default_factory=dict)


class FinalStatus(str, Enum):
    produced = "produced"
    empty = "empty"
    failed = "failed"
    timeout = "timeout"
    cancelled = "cancelled"


class FinalOutput(StrictModel):
    status: FinalStatus
    evidence_id: Optional[str] = None


class AuditOnly(StrictModel):
    gold: Optional[str] = None
    gold_hash: Optional[HashValue] = None
    rubric_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class Episode(StrictModel):
    schema_version: str = Field(default="1.0", pattern=r"^(0\.1|1\.0)$")
    episode_id: str = Field(min_length=1)
    problem: Problem
    system: System
    run: Run
    adapter: AdapterInfo
    sources: List[Source] = Field(default_factory=list)
    source_observations: List[SourceObservation] = Field(default_factory=list)
    evidence: List[Evidence] = Field(default_factory=list)
    decisions: List[Decision] = Field(default_factory=list)
    provenance_edges: List[ProvenanceEdge] = Field(default_factory=list)
    labels: List[OutcomeLabel] = Field(default_factory=list)
    final_output: FinalOutput
    audit_only: AuditOnly = Field(default_factory=AuditOnly)
    metadata: Dict[str, Any] = Field(default_factory=dict)


JsonValue = Union[None, bool, int, float, str, List["JsonValue"], Dict[str, "JsonValue"]]
