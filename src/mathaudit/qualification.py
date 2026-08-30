# SPDX-License-Identifier: MIT

"""Semantic checks for qualification-run authorization records."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .fingerprint import fingerprint_source_tree, verify_source_fingerprint
from .hashing import sha256_json
from .runprep import verify_input_bundle
from .sampling import verify_sample_manifest_hash

AUTHORIZATION_FORMAT = "mathaudit-compute-authorization-v0.1"
CONTINUATION_AUTHORIZATION_FORMAT = "mathaudit-compute-authorization-v0.2"
SKIP_BOUNDARY_CONTINUATION_AUTHORIZATION_FORMAT = "mathaudit-compute-authorization-v0.3"
CONTINUE_AFTER_FAILURE_AUTHORIZATION_FORMAT = "mathaudit-compute-authorization-v0.4"
REPLACEMENT_AUTHORIZATION_FORMAT = "mathaudit-compute-authorization-v0.5"
AUTHORIZATION_FORMATS = {
    AUTHORIZATION_FORMAT,
    CONTINUATION_AUTHORIZATION_FORMAT,
    SKIP_BOUNDARY_CONTINUATION_AUTHORIZATION_FORMAT,
    CONTINUE_AFTER_FAILURE_AUTHORIZATION_FORMAT,
    REPLACEMENT_AUTHORIZATION_FORMAT,
}
CONTINUATION_AUTHORIZATION_FORMATS = {
    CONTINUATION_AUTHORIZATION_FORMAT,
    SKIP_BOUNDARY_CONTINUATION_AUTHORIZATION_FORMAT,
    CONTINUE_AFTER_FAILURE_AUTHORIZATION_FORMAT,
}
INCREMENTAL_AUTHORIZATION_FORMATS = CONTINUATION_AUTHORIZATION_FORMATS | {
    REPLACEMENT_AUTHORIZATION_FORMAT,
}
DEFAULT_SYSTEM_IDS = ("mathrouter", "icma", "mathgoal")


def qualification_authorization_issues(
    payload: Dict[str, Any],
    *,
    expected_system_ids: Sequence[str] = DEFAULT_SYSTEM_IDS,
    expected_episode_cap: int = 150,
) -> List[str]:
    """Return semantic blockers that a structural JSON Schema cannot express."""

    issues: List[str] = []
    authorization_format = payload.get("format")
    if authorization_format not in AUTHORIZATION_FORMATS:
        issues.append("unsupported authorization format")
    if payload.get("status") != "authorized":
        issues.append("authorization status is not authorized")
    if payload.get("scope") != "qualification_q":
        issues.append("authorization scope is not qualification_q")
    if not payload.get("authorized_by") or not payload.get("authorized_at"):
        issues.append("authorizing person and timestamp are required")
    if payload.get("secrets_recorded") is not False:
        issues.append("secrets_recorded must be false")

    budget = payload.get("total_budget")
    if not isinstance(budget, dict):
        issues.append("total_budget is missing")
    else:
        if authorization_format == AUTHORIZATION_FORMAT:
            if budget.get("episode_cap") != expected_episode_cap:
                issues.append("qualification episode_cap must equal %d" % expected_episode_cap)
        else:
            episode_cap = budget.get("episode_cap")
            if (
                not isinstance(episode_cap, int)
                or isinstance(episode_cap, bool)
                or not 1 <= episode_cap <= expected_episode_cap
            ):
                issues.append("continuation episode_cap must be in [1, %d]" % expected_episode_cap)
        token_cap = budget.get("token_cap")
        if not isinstance(token_cap, int) or isinstance(token_cap, bool) or token_cap <= 0:
            issues.append("a positive hard total token_cap is required")
        currency = budget.get("currency")
        monetary_cap = budget.get("monetary_cap")
        if not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
            issues.append("a three-letter budget currency is required")
        if not isinstance(monetary_cap, (int, float)) or isinstance(monetary_cap, bool) or monetary_cap <= 0:
            issues.append("a positive hard monetary_cap is required")
        wall_time_cap = budget.get("summed_wall_time_cap_s")
        if not isinstance(wall_time_cap, int) or isinstance(wall_time_cap, bool) or wall_time_cap <= 0:
            issues.append("a positive hard total summed_wall_time_cap_s is required")

    monetary_accounting = payload.get("monetary_accounting")
    if not isinstance(monetary_accounting, dict):
        issues.append("monetary_accounting is missing")
    else:
        mode = monetary_accounting.get("mode")
        source = monetary_accounting.get("evidence_source")
        if not isinstance(source, str) or not source.strip():
            issues.append("monetary_accounting.evidence_source is required")
        input_rate = monetary_accounting.get("input_cny_per_million_tokens")
        output_rate = monetary_accounting.get("output_cny_per_million_tokens")
        if mode == "free_quota":
            if monetary_accounting.get("free_quota_confirmed") is not True:
                issues.append("free-quota accounting requires explicit confirmation")
            if input_rate not in (None, 0) or output_rate not in (None, 0):
                issues.append("free-quota accounting must not declare positive token rates")
        elif mode == "token_tariff":
            for field, value in (
                ("input_cny_per_million_tokens", input_rate),
                ("output_cny_per_million_tokens", output_rate),
            ):
                if (
                    not isinstance(value, (int, float))
                    or isinstance(value, bool)
                    or value < 0
                ):
                    issues.append("monetary_accounting.%s must be nonnegative" % field)
        else:
            issues.append("monetary_accounting.mode must be free_quota or token_tariff")

    stop = payload.get("stop_policy")
    if not isinstance(stop, dict):
        issues.append("stop_policy is missing")
    else:
        failure_rate = stop.get("quota_or_transport_failure_rate")
        if not isinstance(failure_rate, (int, float)) or not 0 < failure_rate <= 0.05:
            issues.append("quota/transport stop rate must be in (0, 0.05]")
        continue_after_failure = authorization_format in {
            CONTINUE_AFTER_FAILURE_AUTHORIZATION_FORMAT,
            REPLACEMENT_AUTHORIZATION_FORMAT,
        }
        if continue_after_failure:
            if stop.get("continue_after_episode_failure") is not True:
                issues.append("continue-after-failure mode must be explicitly enabled")
            if stop.get("stop_on_task_dependent_missingness") is not False:
                issues.append("continue-after-failure mode must disable task-missingness batch stop")
            if stop.get("stop_on_trace_loss") is not False:
                issues.append("continue-after-failure mode must disable trace-loss batch stop")
            if stop.get("stop_on_quota_or_transport_failure_rate") is not False:
                issues.append("continue-after-failure mode must disable failure-rate batch stop")
        else:
            if stop.get("stop_on_task_dependent_missingness") is not True:
                issues.append("task-dependent missingness must be a stop condition")
            if stop.get("stop_on_trace_loss") is not True:
                issues.append("trace loss must be a stop condition")

    systems = payload.get("systems")
    if not isinstance(systems, list):
        issues.append("systems must be a list")
        systems = []
    ids = [item.get("system_id") for item in systems if isinstance(item, dict)]
    if sorted(ids) != sorted(expected_system_ids):
        issues.append("authorization must contain each registered system exactly once")
    token_caps = []
    monetary_caps = []
    wall_time_caps = []
    for item in systems:
        if not isinstance(item, dict):
            issues.append("system authorization entry must be an object")
            continue
        system_id = str(item.get("system_id") or "<unknown>")
        for field in ("provider", "model", "endpoint_class", "endpoint_url", "retry_policy"):
            value = item.get(field)
            if not isinstance(value, str) or not value.strip():
                issues.append("%s.%s is required" % (system_id, field))
        endpoint = "%s %s" % (
            str(item.get("endpoint_class") or ""),
            str(item.get("endpoint_url") or ""),
        )
        if re.search(r"(?i)(api[_-]?key|token|secret|password)=|://[^/@:]+:[^/@]+@", endpoint):
            issues.append("%s.endpoint_class appears to contain a credential" % system_id)
        if item.get("endpoint_available") is not True:
            issues.append("%s endpoint availability is not confirmed" % system_id)
        for field in ("concurrency", "episode_timeout_s", "max_output_tokens"):
            value = item.get(field)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                issues.append("%s.%s must be a positive integer" % (system_id, field))
        episode_cap = item.get("episode_cap")
        if authorization_format == AUTHORIZATION_FORMAT:
            if episode_cap != 50:
                issues.append("%s.episode_cap must equal 50" % system_id)
        elif authorization_format == REPLACEMENT_AUTHORIZATION_FORMAT:
            if (
                not isinstance(episode_cap, int)
                or isinstance(episode_cap, bool)
                or not 0 <= episode_cap <= 50
            ):
                issues.append("%s.episode_cap must be in [0, 50]" % system_id)
        elif (
            not isinstance(episode_cap, int)
            or isinstance(episode_cap, bool)
            or not 1 <= episode_cap <= 50
        ):
            issues.append("%s.episode_cap must be in [1, 50]" % system_id)
        for field, accumulator in (
            ("token_cap", token_caps),
            ("monetary_cap", monetary_caps),
            ("summed_wall_time_cap_s", wall_time_caps),
        ):
            value = item.get(field)
            allow_zero = (
                authorization_format == REPLACEMENT_AUTHORIZATION_FORMAT
                and episode_cap == 0
            )
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or value < 0
                or (value == 0 and not allow_zero)
            ):
                issues.append(
                    "%s.%s must be positive for scheduled systems and zero only for unscheduled replacement systems"
                    % (system_id, field)
                )
            else:
                accumulator.append(value)
        if isinstance(budget, dict) and item.get("currency") != budget.get("currency"):
            issues.append("%s.currency must match the total budget" % system_id)
        parameters = item.get("parameters")
        gateway_timeout = None
        if not isinstance(parameters, dict):
            issues.append("%s.parameters must be an object" % system_id)
        else:
            gateway_timeout = parameters.get("gateway_upstream_timeout_s")
        if gateway_timeout is None and authorization_format in INCREMENTAL_AUTHORIZATION_FORMATS:
            issues.append("%s.gateway_upstream_timeout_s is required" % system_id)
        elif gateway_timeout is not None and (
            not isinstance(gateway_timeout, (int, float))
            or isinstance(gateway_timeout, bool)
            or gateway_timeout <= 0
        ):
            issues.append("%s.gateway_upstream_timeout_s must be positive" % system_id)
        if system_id == "mathgoal" and isinstance(gateway_timeout, (int, float)):
            request_retries = parameters.get("gateway_pre_response_transport_retries", 0)
            client_timeout = parameters.get("llm_timeout_seconds")
            required_envelope = gateway_timeout * (1 + request_retries)
            if (
                not isinstance(client_timeout, (int, float))
                or isinstance(client_timeout, bool)
                or client_timeout <= required_envelope
            ):
                issues.append(
                    "mathgoal.llm_timeout_seconds must exceed the full gateway retry envelope"
                )
        retry_control = item.get("retry_control")
        expected_retry_control = {
            "max_retries": 1,
            "eligible_failure_class": "pre_response_transport_failure_only",
            "forbid_after_any_response": True,
            "forbid_on_parse_failure": True,
            "forbid_on_tool_failure": True,
        }
        if retry_control != expected_retry_control:
            issues.append(
                "%s.retry_control must allow at most one pre-response transport retry "
                "and forbid response/parse/tool retries" % system_id
            )
    if isinstance(budget, dict):
        if authorization_format in INCREMENTAL_AUTHORIZATION_FORMATS:
            system_episode_caps = [
                item.get("episode_cap")
                for item in systems
                if isinstance(item, dict)
                and isinstance(item.get("episode_cap"), int)
                and not isinstance(item.get("episode_cap"), bool)
            ]
            if (
                len(system_episode_caps) == len(expected_system_ids)
                and sum(system_episode_caps) != budget.get("episode_cap")
            ):
                issues.append("continuation system episode caps must sum to total episode_cap")
        comparisons = (
            (token_caps, budget.get("token_cap"), "token"),
            (monetary_caps, budget.get("monetary_cap"), "monetary"),
            (wall_time_caps, budget.get("summed_wall_time_cap_s"), "wall-time"),
        )
        for values, total, label in comparisons:
            if values and isinstance(total, (int, float)) and sum(values) > total:
                issues.append("per-system %s caps exceed the total cap" % label)

    replacement = payload.get("replacement")
    if authorization_format == REPLACEMENT_AUTHORIZATION_FORMAT:
        if not isinstance(replacement, dict):
            issues.append("replacement provenance is required")
        else:
            sequences = replacement.get("replacement_sequences")
            if (
                not isinstance(sequences, list)
                or not sequences
                or any(
                    not isinstance(sequence, int)
                    or isinstance(sequence, bool)
                    or not 0 <= sequence < expected_episode_cap
                    for sequence in sequences
                )
                or sequences != sorted(set(sequences))
            ):
                issues.append("replacement sequences must be sorted unique integers in [0, 149]")
            if (
                isinstance(sequences, list)
                and isinstance(budget, dict)
                and budget.get("episode_cap") != len(sequences)
            ):
                issues.append("replacement episode_cap must equal replacement sequence count")
            if replacement.get("final_target_episode_count") != expected_episode_cap:
                issues.append("replacement final target must equal %d" % expected_episode_cap)
            if replacement.get("complete_slot_count_before_replacement") != (
                expected_episode_cap - len(sequences)
                if isinstance(sequences, list)
                else None
            ):
                issues.append("replacement prior complete-slot count is inconsistent")
            provenance_fields = (
                ("source_state_sha256", "source_closeout_sha256")
                if "source_state_sha256" in replacement
                or "source_closeout_sha256" in replacement
                else ("source_q11_state_sha256", "source_q11_closeout_sha256")
            )
            if "source_state_sha256" in replacement and not isinstance(
                replacement.get("source_run_id"), str
            ):
                issues.append("replacement.source_run_id is required for chained replacements")
            for field in (
                "source_schedule_plan_sha256",
                "source_inventory_sha256",
                *provenance_fields,
            ):
                value = replacement.get(field)
                if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
                    issues.append("replacement.%s must be a sha256 digest" % field)
            prior_attempts = replacement.get("prior_attempted_episode_count")
            cumulative_attempt_cap = replacement.get("cumulative_attempted_episode_cap")
            if (
                not isinstance(prior_attempts, int)
                or isinstance(prior_attempts, bool)
                or not isinstance(cumulative_attempt_cap, int)
                or isinstance(cumulative_attempt_cap, bool)
                or cumulative_attempt_cap
                != prior_attempts + (len(sequences) if isinstance(sequences, list) else 0)
            ):
                issues.append("replacement cumulative attempted-episode accounting is inconsistent")
            prior_reserved_tokens = replacement.get("prior_reserved_token_upper")
            cumulative_token_cap = replacement.get("cumulative_token_cap")
            local_token_cap = budget.get("token_cap") if isinstance(budget, dict) else None
            if (
                not isinstance(prior_reserved_tokens, int)
                or isinstance(prior_reserved_tokens, bool)
                or not isinstance(cumulative_token_cap, int)
                or isinstance(cumulative_token_cap, bool)
                or not isinstance(local_token_cap, int)
                or isinstance(local_token_cap, bool)
                or prior_reserved_tokens + local_token_cap > cumulative_token_cap
            ):
                issues.append("replacement cumulative token accounting exceeds its hard cap")
            prior_wall_time = replacement.get("prior_summed_wall_time_s")
            cumulative_wall_cap = replacement.get("cumulative_wall_time_cap_s")
            local_wall_cap = (
                budget.get("summed_wall_time_cap_s") if isinstance(budget, dict) else None
            )
            if (
                not isinstance(prior_wall_time, (int, float))
                or isinstance(prior_wall_time, bool)
                or not isinstance(cumulative_wall_cap, int)
                or isinstance(cumulative_wall_cap, bool)
                or not isinstance(local_wall_cap, int)
                or isinstance(local_wall_cap, bool)
                or prior_wall_time + local_wall_cap > cumulative_wall_cap
            ):
                issues.append("replacement cumulative wall-time accounting exceeds its hard cap")
            if replacement.get("cumulative_monetary_cap_cny") != 10:
                issues.append("replacement cumulative CNY hard cap must remain 10")

    continuation = payload.get("continuation")
    if authorization_format in CONTINUATION_AUTHORIZATION_FORMATS:
        if not isinstance(continuation, dict):
            issues.append("continuation provenance is required")
        else:
            prefix = continuation.get("completed_prefix_episode_count")
            restart = continuation.get("restart_sequence")
            target = continuation.get("final_target_episode_count")
            skip_failed_boundary = (
                authorization_format
                in {
                    SKIP_BOUNDARY_CONTINUATION_AUTHORIZATION_FORMAT,
                    CONTINUE_AFTER_FAILURE_AUTHORIZATION_FORMAT,
                }
            )
            if (
                not isinstance(prefix, int)
                or isinstance(prefix, bool)
                or not 1 <= prefix < expected_episode_cap
            ):
                issues.append("continuation completed prefix is invalid")
            if skip_failed_boundary:
                if (
                    isinstance(prefix, int)
                    and not isinstance(prefix, bool)
                    and restart != prefix + 1
                ) or not isinstance(prefix, int):
                    issues.append(
                        "skip-boundary continuation restart_sequence must equal completed prefix + 1"
                    )
                if continuation.get("deferred_replacement_count") != 1:
                    issues.append("skip-boundary continuation must defer exactly one replacement")
                deferred_sequence = continuation.get("deferred_replacement_sequence")
                deferred_ok = (
                    isinstance(prefix, int)
                    and (
                        deferred_sequence == prefix
                        if authorization_format
                        == SKIP_BOUNDARY_CONTINUATION_AUTHORIZATION_FORMAT
                        else isinstance(deferred_sequence, int)
                        and not isinstance(deferred_sequence, bool)
                        and 1 <= deferred_sequence < prefix
                    )
                )
                if not deferred_ok:
                    issues.append(
                        "skip-boundary continuation must identify the failed boundary sequence"
                    )
            elif restart != prefix:
                issues.append("continuation restart_sequence must equal completed prefix")
            if target != expected_episode_cap:
                issues.append("continuation final target must equal %d" % expected_episode_cap)
            if (
                isinstance(prefix, int)
                and not isinstance(prefix, bool)
                and isinstance(budget, dict)
                and budget.get("episode_cap")
                != expected_episode_cap - prefix - (1 if skip_failed_boundary else 0)
            ):
                issues.append("continuation episode_cap does not match the continuation mode")
    return issues


def verify_qualification_authorization(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Raise on any semantic blocker and return a redacted approval summary."""

    issues = qualification_authorization_issues(payload)
    if issues:
        raise ValueError("qualification authorization is not runnable: " + "; ".join(issues))
    return {
        "authorization_id": payload["authorization_id"],
        "status": payload["status"],
        "scope": payload["scope"],
        "episode_cap": payload["total_budget"]["episode_cap"],
        "token_cap": payload["total_budget"]["token_cap"],
        "currency": payload["total_budget"]["currency"],
        "monetary_cap": payload["total_budget"]["monetary_cap"],
        "monetary_accounting_mode": payload["monetary_accounting"]["mode"],
        "system_ids": sorted(item["system_id"] for item in payload["systems"]),
        "secrets_recorded": False,
    }


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _schema_errors(payload: Any, schema_path: Path) -> List[str]:
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        return ["jsonschema extra is not installed"]
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    return [
        "%s: %s" % (".".join(str(part) for part in error.path) or "$", error.message)
        for error in sorted(validator.iter_errors(payload), key=lambda item: list(item.path))
    ]


def _resolve_path(workspace: Path, spec: Dict[str, Any], environment: Dict[str, str]) -> Path:
    if "path" in spec:
        candidate = workspace / str(spec["path"])
    elif "root_env" in spec:
        variable = str(spec["root_env"])
        value = environment.get(variable)
        if not value:
            raise ValueError("required environment variable is unset: %s" % variable)
        candidate = Path(value)
    else:
        raise ValueError("path specification requires path or root_env")
    return candidate.resolve()


def _run_git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode:
        raise ValueError("git command failed")
    return result.stdout.strip()


def _registered_run_environment(
    config: Dict[str, Any],
    workspace: Path,
    system_id: str,
    fallback_lock_sha256: str,
    environment: Dict[str, str],
) -> Dict[str, Any]:
    """Resolve the interpreter registration used by a reference run manifest.

    The package's own ``uv.lock`` is only a fallback for legacy configurations.
    A registered reference environment is identified by its realized normalized
    distribution snapshot, because that is the environment the harness actually
    runs in.
    """

    matches = [
        item
        for item in config.get("reference_environments") or []
        if item.get("system_id") == system_id
    ]
    if not matches:
        return {
            "os": platform.platform(),
            "python": platform.python_version(),
            "dependency_lock_sha256": fallback_lock_sha256,
            "container_image": None,
        }
    if len(matches) != 1:
        raise ValueError("reference environment is not unique: %s" % system_id)
    item = matches[0]
    python_path = _resolve_path(workspace, {"path": item["python_path"]}, environment)
    snapshot_path = _resolve_path(
        workspace, {"path": item["snapshot_path"]}, environment
    )
    if not snapshot_path.is_file():
        raise ValueError("reference environment snapshot is missing: %s" % system_id)
    version = str(item.get("expected_python_version") or "").strip()
    if not version:
        raise ValueError("reference Python version is missing: %s" % system_id)
    try:
        realized_platform = subprocess.run(
            [
                str(python_path),
                "-c",
                "import platform; print(platform.platform())",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError("reference Python platform probe failed: %s" % system_id) from exc
    if not realized_platform:
        raise ValueError("reference Python platform probe returned no value: %s" % system_id)
    return {
        # Bind the manifest to the interpreter that will run the harness, not
        # to the executor's possibly different Python/OS reporting layer.
        "os": realized_platform,
        "python": version,
        "dependency_lock_sha256": _file_sha256(snapshot_path),
        "container_image": None,
    }


def run_qualification_preflight(
    config_path: Path,
    *,
    environment: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Run every provider-free gate before a qualification runner may start."""

    config = json.loads(config_path.read_text(encoding="utf-8"))
    if config.get("format") != "mathaudit-qualification-preflight-v0.1":
        raise ValueError("unsupported qualification preflight format")
    workspace = (config_path.parent / str(config.get("workspace_root") or ".")).resolve()
    env = dict(os.environ if environment is None else environment)
    checks: List[Dict[str, str]] = []

    def record(check_id: str, action: Any) -> Any:
        try:
            detail = action()
            checks.append({"check_id": check_id, "status": "pass", "detail": str(detail)})
            return detail
        except Exception as exc:
            checks.append({"check_id": check_id, "status": "fail", "detail": str(exc)})
            return None

    lock_spec = config["dependency_lock"]
    lock_path = _resolve_path(workspace, lock_spec, env)
    lock_hash = record(
        "dependency_lock",
        lambda: _verify_file_hash(lock_path, str(lock_spec["expected_sha256"])),
    )

    authorization_spec = config["authorization"]
    authorization_path = _resolve_path(workspace, authorization_spec, env)
    authorization: Optional[Dict[str, Any]] = None

    def check_authorization() -> str:
        nonlocal authorization
        if not authorization_path.is_file():
            raise ValueError("authorization record is missing")
        authorization = json.loads(authorization_path.read_text(encoding="utf-8"))
        schema_path = _resolve_path(
            workspace, {"path": authorization_spec["schema"]}, env
        )
        errors = _schema_errors(authorization, schema_path)
        if errors:
            raise ValueError("authorization Schema: " + "; ".join(errors))
        summary = verify_qualification_authorization(authorization)
        return "%s; %d episodes" % (summary["authorization_id"], summary["episode_cap"])

    record("compute_authorization", check_authorization)

    source_system_ids: List[str] = []
    source_fingerprints: Dict[str, str] = {}
    for item in config.get("sources") or []:
        system_id = str(item["system_id"])
        root = None
        try:
            root = _resolve_path(workspace, item, env)
        except Exception as exc:
            checks.append(
                {"check_id": "source:%s" % system_id, "status": "fail", "detail": str(exc)}
            )
            continue

        if item.get("kind") == "git":

            def check_git(
                item: Dict[str, Any] = item,
                root: Path = root,
                system_id: str = system_id,
            ) -> str:
                head = _run_git(root, "rev-parse", "HEAD")
                if head != item["expected_commit"]:
                    raise ValueError("Git commit drift")
                if item.get("require_clean", True) and _run_git(
                    root, "status", "--porcelain", "--untracked-files=all"
                ):
                    raise ValueError("Git worktree is not clean")
                for critical in item.get("critical_files") or []:
                    try:
                        _verify_file_hash(root / critical["path"], critical["sha256"])
                    except ValueError as exc:
                        raise ValueError(
                            "critical file drift: %s" % critical["path"]
                        ) from exc
                fingerprint = fingerprint_source_tree(root, system_id=system_id)
                if fingerprint["manifest_sha256"] != item["run_source_fingerprint"]:
                    raise ValueError("full Git source-tree fingerprint drift")
                source_system_ids.append(system_id)
                source_fingerprints[system_id] = fingerprint["manifest_sha256"]
                return "Git commit and %d critical file(s) verified" % len(
                    item.get("critical_files") or []
                )

            record("source:%s" % system_id, check_git)
        elif item.get("kind") == "fingerprint":

            def check_tree(
                item: Dict[str, Any] = item,
                root: Path = root,
                system_id: str = system_id,
            ) -> str:
                manifest_path = _resolve_path(
                    workspace, {"path": item["manifest"]}, env
                )
                if not manifest_path.is_file():
                    raise ValueError("source fingerprint manifest is missing")
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                summary = verify_source_fingerprint(root, manifest)
                if summary["system_id"] != system_id:
                    raise ValueError("source manifest system mismatch")
                source_system_ids.append(system_id)
                source_fingerprints[system_id] = summary["manifest_sha256"]
                return "%d files; %s" % (
                    summary["file_count"],
                    summary["manifest_sha256"],
                )

            record("source:%s" % system_id, check_tree)
        else:
            checks.append(
                {
                    "check_id": "source:%s" % system_id,
                    "status": "fail",
                    "detail": "unsupported source check kind",
                }
            )

    expected_systems = sorted(config.get("expected_system_ids") or DEFAULT_SYSTEM_IDS)
    record(
        "source_set",
        lambda: _verify_system_set(source_system_ids, expected_systems),
    )

    for index, item in enumerate(config.get("sample_manifests") or []):

        def check_sample(item: Dict[str, Any] = item) -> str:
            path = _resolve_path(workspace, item, env)
            if not path.is_file():
                raise ValueError("sample manifest is missing")
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not verify_sample_manifest_hash(payload):
                raise ValueError("sample manifest self-hash mismatch")
            if payload["manifest_sha256"] != item["expected_manifest_sha256"]:
                raise ValueError("sample manifest differs from preregistration")
            selected = payload.get("selected")
            if not isinstance(selected, list) or not selected:
                raise ValueError("sample manifest has no selected records")
            return "%d selected; %s" % (len(selected), payload["stratum"])

        record("sample_manifest:%d" % index, check_sample)

    bundle_spec = config["input_bundle"]

    def check_bundle() -> str:
        path = _resolve_path(workspace, bundle_spec, env)
        if not path.is_dir():
            raise ValueError("input bundle is missing")
        summary = verify_input_bundle(path)
        if summary["task_count"] != bundle_spec["expected_task_count"]:
            raise ValueError("input bundle task-count drift")
        if summary["bundle_sha256"] != bundle_spec["expected_bundle_sha256"]:
            raise ValueError("input bundle hash drift")
        return "%d tasks; gold separation verified" % summary["task_count"]

    record("input_bundle", check_bundle)

    for item in config.get("required_artifacts") or []:
        record(
            "artifact:%s" % item["artifact_id"],
            lambda item=item: _verify_file_hash(
                _resolve_path(workspace, item, env), str(item["expected_sha256"])
            ),
        )

    for item in config.get("artifact_trees") or []:

        def check_artifact_tree(item: Dict[str, Any] = item) -> str:
            tree_root = _resolve_path(workspace, {"path": item["path"]}, env)
            manifest_path = _resolve_path(
                workspace, {"path": item["manifest"]}, env
            )
            if not manifest_path.is_file():
                raise ValueError("artifact-tree fingerprint manifest is missing")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            summary = verify_source_fingerprint(tree_root, manifest)
            return "%d files; %s" % (
                summary["file_count"],
                summary["manifest_sha256"],
            )

        record("artifact_tree:%s" % item["artifact_id"], check_artifact_tree)

    environment_system_ids: List[str] = []
    for item in config.get("reference_environments") or []:
        system_id = str(item["system_id"])

        def check_environment(
            item: Dict[str, Any] = item,
            system_id: str = system_id,
        ) -> str:
            python_path = _resolve_path(
                workspace, {"path": item["python_path"]}, env
            )
            detail = _verify_reference_environment(
                python_path,
                _resolve_path(workspace, {"path": item["snapshot_path"]}, env),
                str(item["expected_python_version"]),
            )
            if "entrypoint_path" in item:
                entrypoint_path = _resolve_path(
                    workspace, {"path": item["entrypoint_path"]}, env
                )
            else:
                entrypoint_root = _resolve_path(
                    workspace, {"root_env": item["entrypoint_root_env"]}, env
                )
                entrypoint_path = (
                    entrypoint_root / str(item["entrypoint_relative_path"])
                ).resolve()
            smoke = _verify_entrypoint_help(python_path, entrypoint_path, env)
            environment_system_ids.append(system_id)
            return detail + "; " + smoke

        record("environment:%s" % system_id, check_environment)
    if config.get("reference_environments"):
        record(
            "environment_set",
            lambda: _verify_system_set(environment_system_ids, expected_systems),
        )

    run_schema_path = _resolve_path(
        workspace, {"path": config["run_manifest_schema"]}, env
    )
    run_system_ids: List[str] = []
    for item in config.get("run_manifests") or []:
        system_id = str(item["system_id"])

        def check_run_manifest(item: Dict[str, Any] = item, system_id: str = system_id) -> str:
            path = _resolve_path(workspace, item, env)
            if not path.is_file():
                raise ValueError("run manifest is missing")
            payload = json.loads(path.read_text(encoding="utf-8"))
            errors = _schema_errors(payload, run_schema_path)
            if errors:
                raise ValueError("run manifest Schema: " + "; ".join(errors))
            if payload["system"]["system_id"] != system_id:
                raise ValueError("run manifest system mismatch")
            if payload["system"]["source_fingerprint"] != source_fingerprints.get(system_id):
                raise ValueError("run manifest source fingerprint mismatch")
            if payload["study_phase"] != "qualification" or payload["status"] != "planned":
                raise ValueError("run manifest is not a planned qualification")
            if payload["outcome_blind"] is not True or payload["secrets_recorded"] is not False:
                raise ValueError("run manifest violates blinding/secrets policy")
            expected_run_cap = 50
            if authorization is not None:
                expected_run_cap = next(
                    entry["episode_cap"]
                    for entry in authorization["systems"]
                    if entry["system_id"] == system_id
                )
            if payload["budget"]["episode_cap"] != expected_run_cap:
                raise ValueError("Q system run episode cap differs from authorization")
            expected_environment = _registered_run_environment(
                config, workspace, system_id, str(lock_hash or ""), env
            )
            if payload["environment"] != expected_environment:
                raise ValueError("run manifest reference-environment registration mismatch")
            if authorization is not None:
                auth = next(
                    entry for entry in authorization["systems"] if entry["system_id"] == system_id
                )
                comparisons = {
                    "provider": auth["provider"],
                    "model": auth["model"],
                    "model_revision": auth["model_revision"],
                    "endpoint_class": auth["endpoint_class"],
                    "endpoint_url": auth["endpoint_url"],
                    "parameters": auth["parameters"],
                    "episode_timeout_s": auth["episode_timeout_s"],
                    "concurrency": auth["concurrency"],
                    "max_output_tokens": auth["max_output_tokens"],
                    "retry_policy": auth["retry_policy"],
                    "retry_control": auth["retry_control"],
                }
                if any(payload["runtime"].get(key) != value for key, value in comparisons.items()):
                    raise ValueError("run manifest runtime differs from authorization")
                budget_comparisons = {
                    "episode_cap": auth["episode_cap"],
                    "token_cap": auth["token_cap"],
                    "currency": auth["currency"],
                    "monetary_cap": auth["monetary_cap"],
                    "summed_wall_time_cap_s": auth["summed_wall_time_cap_s"],
                    "monetary_accounting": authorization["monetary_accounting"],
                }
                if any(
                    payload["budget"].get(key) != value
                    for key, value in budget_comparisons.items()
                ):
                    raise ValueError("run manifest budget differs from authorization")
            run_system_ids.append(system_id)
            return "planned, outcome-blind, %d-episode cap" % expected_run_cap

        record("run_manifest:%s" % system_id, check_run_manifest)

    record(
        "run_manifest_set",
        lambda: _verify_system_set(run_system_ids, expected_systems),
    )
    report = {
        "format": "mathaudit-qualification-preflight-report-v0.1",
        "ready": all(item["status"] == "pass" for item in checks),
        "pass_count": sum(item["status"] == "pass" for item in checks),
        "fail_count": sum(item["status"] == "fail" for item in checks),
        "checks": checks,
    }
    report["report_sha256"] = sha256_json(report)
    return report


def _verify_file_hash(path: Path, expected: str) -> str:
    if not path.is_file():
        raise ValueError("required file is missing")
    observed = _file_sha256(path)
    if observed != expected:
        raise ValueError("file hash drift")
    return observed


def _verify_system_set(observed: Sequence[str], expected: Sequence[str]) -> str:
    if sorted(observed) != sorted(expected):
        raise ValueError("registered system set mismatch")
    return "%d registered systems" % len(expected)


def _verify_reference_environment(
    python_path: Path,
    snapshot_path: Path,
    expected_python_version: str,
) -> str:
    """Compare an interpreter's realized distributions with a frozen snapshot."""

    if not python_path.is_file():
        raise ValueError("reference Python interpreter is missing")
    if not snapshot_path.is_file():
        raise ValueError("reference environment snapshot is missing")
    script = r"""
import importlib.metadata as metadata
import json
import platform
import re

def canonical(name):
    return re.sub(r"[-_.]+", "-", name).lower()

rows = []
for distribution in metadata.distributions():
    name = distribution.metadata.get("Name")
    if name:
        rows.append(canonical(name) + "==" + distribution.version)
print(json.dumps({"python": platform.python_version(), "distributions": sorted(set(rows))}))
"""
    result = subprocess.run(
        [str(python_path), "-c", script],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        # Do not let the auditor's source checkout (and its local .egg-info)
        # contaminate the isolated reference environment's distribution set.
        env={key: value for key, value in os.environ.items() if key not in {"PYTHONPATH", "PYTHONHOME"}},
    )
    if result.returncode:
        raise ValueError("reference interpreter metadata probe failed")
    try:
        observed = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("reference interpreter metadata probe returned invalid JSON") from exc
    if observed.get("python") != expected_python_version:
        raise ValueError("reference Python version drift")
    expected_rows = []
    for line_number, line in enumerate(
        snapshot_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        value = line.strip()
        if not value:
            continue
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*==[^\s=]+", value):
            raise ValueError(
                "invalid normalized environment snapshot line %d" % line_number
            )
        name, version = value.split("==", 1)
        canonical_name = re.sub(r"[-_.]+", "-", name).lower()
        expected_rows.append(canonical_name + "==" + version)
    if sorted(set(expected_rows)) != observed.get("distributions"):
        raise ValueError("installed distribution snapshot drift")
    return "%s; %d distributions" % (observed["python"], len(expected_rows))


def _verify_entrypoint_help(
    python_path: Path,
    entrypoint_path: Path,
    environment: Dict[str, str],
) -> str:
    """Import a real reference entry point through its no-contact help path."""

    if not entrypoint_path.is_file():
        raise ValueError("reference entry point is missing")
    sanitized_environment = dict(environment)
    sanitized_environment.pop("PYTHONPATH", None)
    sanitized_environment.pop("PYTHONHOME", None)
    for name in (
        "INTERN_API_KEY",
        "LLM_API_KEY",
        "MATHROUTER_INTERN_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
    ):
        sanitized_environment.pop(name, None)
    result = subprocess.run(
        [str(python_path), str(entrypoint_path), "--help"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        cwd=str(entrypoint_path.parent),
        env=sanitized_environment,
    )
    if result.returncode or "usage:" not in result.stdout.lower():
        raise ValueError("reference entry-point help smoke test failed")
    return "credential-stripped --help passed"


def prepare_qualification_run_manifests(
    config_path: Path,
    authorization_path: Path,
    output_dir: Path,
) -> Dict[str, Any]:
    """Compile three planned run manifests only from an approved authorization."""

    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError("output directory must be absent or empty: %s" % output_dir)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if config.get("format") != "mathaudit-qualification-preflight-v0.1":
        raise ValueError("unsupported qualification preflight format")
    workspace = (config_path.parent / str(config.get("workspace_root") or ".")).resolve()
    authorization = json.loads(authorization_path.read_text(encoding="utf-8"))
    verify_qualification_authorization(authorization)
    authorization_schema = _resolve_path(
        workspace, {"path": config["authorization"]["schema"]}, dict(os.environ)
    )
    errors = _schema_errors(authorization, authorization_schema)
    if errors:
        raise ValueError("authorization Schema: " + "; ".join(errors))

    lock_spec = config["dependency_lock"]
    lock_path = _resolve_path(workspace, lock_spec, dict(os.environ))
    lock_hash = _verify_file_hash(lock_path, lock_spec["expected_sha256"])
    bundle_spec = config["input_bundle"]
    bundle_root = _resolve_path(workspace, bundle_spec, dict(os.environ))
    bundle = verify_input_bundle(bundle_root)
    if (
        bundle["task_count"] != bundle_spec["expected_task_count"]
        or bundle["bundle_sha256"] != bundle_spec["expected_bundle_sha256"]
    ):
        raise ValueError("input bundle differs from the qualification registration")

    source_by_id = {item["system_id"]: item for item in config["sources"]}
    expected_systems = sorted(config.get("expected_system_ids") or DEFAULT_SYSTEM_IDS)
    _verify_system_set(list(source_by_id), expected_systems)
    sample_members = []
    for item in config["sample_manifests"]:
        path = _resolve_path(workspace, item, dict(os.environ))
        payload = json.loads(path.read_text(encoding="utf-8"))
        if (
            not verify_sample_manifest_hash(payload)
            or payload["manifest_sha256"] != item["expected_manifest_sha256"]
        ):
            raise ValueError("sample manifest differs from the qualification registration")
        sample_members.append(
            {
                "dataset_id": payload["dataset_id"],
                "dataset_version": payload.get("dataset_version"),
                "stratum": payload["stratum"],
                "selected_count": len(payload["selected"]),
                "manifest_sha256": payload["manifest_sha256"],
            }
        )
    sample_set = {
        "format": "mathaudit-qualification-sample-set-v0.1",
        "selected_count": sum(item["selected_count"] for item in sample_members),
        "strata": [item["stratum"] for item in sample_members],
        "members": sample_members,
        "input_bundle_sha256": bundle["bundle_sha256"],
    }
    sample_set["sample_set_sha256"] = sha256_json(sample_set)
    if sample_set["selected_count"] != 50:
        raise ValueError("qualification sample set must contain exactly 50 tasks")

    output_dir.mkdir(parents=True, exist_ok=True)
    sample_set_path = output_dir / "qualification_sample_set.json"
    sample_set_path.write_text(
        json.dumps(sample_set, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    written = [sample_set_path]
    for system_auth in authorization["systems"]:
        system_id = system_auth["system_id"]
        source = source_by_id[system_id]
        payload = {
            "format": "mathaudit-run-manifest-v0.1",
            "run_id": "qualification-q-%s-%s"
            % (system_id, authorization["authorization_id"]),
            "study_phase": "qualification",
            "status": "planned",
            "system": {
                "system_id": system_id,
                "name": source["name"],
                "version": source["version"],
                "source_fingerprint": source["run_source_fingerprint"],
                "adapter_name": source["adapter_name"],
                "adapter_version": source["adapter_version"],
                "adapter_fidelity": source["adapter_fidelity"],
            },
            "sample_manifest": {
                "relative_path": "qualification_sample_set.json",
                "sha256": sample_set["sample_set_sha256"],
                "selected_count": sample_set["selected_count"],
                "strata": sample_set["strata"],
            },
            "runtime": {
                "provider": system_auth["provider"],
                "model": system_auth["model"],
                "model_revision": system_auth["model_revision"],
                "endpoint_class": system_auth["endpoint_class"],
                "endpoint_url": system_auth["endpoint_url"],
                "parameters": system_auth["parameters"],
                "episode_timeout_s": system_auth["episode_timeout_s"],
                "concurrency": system_auth["concurrency"],
                "max_output_tokens": system_auth["max_output_tokens"],
                "retry_policy": system_auth["retry_policy"],
                "retry_control": system_auth["retry_control"],
            },
            "budget": {
                "episode_cap": system_auth["episode_cap"],
                "token_cap": system_auth["token_cap"],
                "currency": system_auth["currency"],
                "monetary_cap": system_auth["monetary_cap"],
                "summed_wall_time_cap_s": system_auth["summed_wall_time_cap_s"],
                "monetary_accounting": authorization["monetary_accounting"],
            },
              "environment": _registered_run_environment(
                  config,
                  workspace,
                  system_id,
                  lock_hash,
                  dict(os.environ),
              ),
            "started_at": None,
            "ended_at": None,
            "counts": {
                "attempted": 0,
                "completed": 0,
                "failed": 0,
                "timed_out": 0,
                "quota_or_transport_failed": 0,
                "excluded": 0,
            },
            "outcome_blind": True,
            "secrets_recorded": False,
            "deviation_log": None,
            "artifacts": [],
            "notes": [
                "Prepared from authorization %s; no provider contact."
                % authorization["authorization_id"]
            ],
        }
        target = output_dir / (system_id + ".json")
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        written.append(target)
    preparation = {
        "format": "mathaudit-run-manifest-preparation-v0.1",
        "authorization_id": authorization["authorization_id"],
        "input_bundle_sha256": bundle["bundle_sha256"],
        "files": [
            {"path": path.name, "sha256": _file_sha256(path)} for path in written
        ],
    }
    preparation["preparation_sha256"] = sha256_json(preparation)
    preparation_path = output_dir / "preparation_manifest.json"
    preparation_path.write_text(
        json.dumps(preparation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return preparation
