"""Shared helpers for built-in adapters."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ..hashing import sha256_json, sha256_text
from ..models import (
    AdapterFidelity,
    AdapterInfo,
    AuditOnly,
    EvidenceContent,
    HashValue,
    Problem,
    Run,
    System,
    Visibility,
)
from .base import ProblemContext, RunContext


def hash_text(value: str) -> HashValue:
    return HashValue(value=sha256_text(value))


def hash_json(value: Any) -> HashValue:
    return HashValue(value=sha256_json(value))


def make_content(
    text: str,
    *,
    normalized_answer: Optional[str] = None,
    structured: Any = None,
    visibility: Visibility = Visibility.private,
) -> EvidenceContent:
    return EvidenceContent(
        visibility=visibility,
        text=text,
        content_hash=hash_text(text),
        normalized_answer=normalized_answer,
        structured=structured,
    )


def base_episode_parts(
    problem: ProblemContext,
    run: RunContext,
    *,
    adapter_name: str,
    adapter_version: str,
    fidelity: AdapterFidelity,
    source_format: str,
    warnings: Optional[List[str]] = None,
) -> Tuple[Problem, System, Run, AdapterInfo, AuditOnly]:
    problem_model = Problem(
        problem_id=problem.problem_id,
        dataset_id=problem.dataset_id,
        dataset_version=problem.dataset_version,
        split=problem.split,
        stratum=problem.stratum,
        domain=problem.domain,
        difficulty=problem.difficulty,
        answer_type=problem.answer_type,
        input_hash=hash_text(problem.statement),
        statement=problem.statement,
        solver_visible_metadata=dict(problem.solver_visible_metadata),
    )
    system_model = System(
        system_id=run.system_id,
        name=run.system_name,
        version=run.system_version,
        harness_family=run.harness_family,
        repository=run.repository,
        commit=run.commit,
        config_hash=hash_json(run.config),
    )
    run_model = Run(
        run_id=run.run_id,
        seed=run.seed,
        budget=dict(run.config.get("budget", {})),
        environment_hash=hash_json(run.environment),
    )
    adapter_model = AdapterInfo(
        name=adapter_name,
        version=adapter_version,
        fidelity=fidelity,
        source_format=source_format,
        warnings=list(warnings or []),
    )
    audit_only = AuditOnly(
        gold=problem.gold,
        gold_hash=hash_text(problem.gold) if problem.gold is not None else None,
    )
    return problem_model, system_model, run_model, adapter_model, audit_only


def first_text(mapping: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = mapping.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def nested_text(mapping: Dict[str, Any], *paths: str) -> str:
    for path in paths:
        value: Any = mapping
        for key in path.split("."):
            if not isinstance(value, dict):
                value = None
                break
            value = value.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""
