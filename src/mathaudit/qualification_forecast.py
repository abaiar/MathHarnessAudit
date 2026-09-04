# SPDX-License-Identifier: MIT

"""Outcome-blind linear resource forecasts from qualification health telemetry."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict, Mapping

from .hashing import sha256_json
from .qualification_closeout import HEALTH_FORMATS, SYSTEM_IDS

FORECAST_FORMAT = "mathaudit-qualification-forecast-v0.1"
DEFAULT_SCENARIOS = {"M": 200, "L": 1000}


def _verify_health(health: Dict[str, Any]) -> None:
    if health.get("format") not in HEALTH_FORMATS:
        raise ValueError("unsupported qualification health format")
    claimed = health.get("health_sha256")
    candidate = copy.deepcopy(health)
    candidate.pop("health_sha256", None)
    if claimed != sha256_json(candidate):
        raise ValueError("qualification health self-hash mismatch")
    if health.get("outcome_blind") is not True:
        raise ValueError("qualification health is not outcome-blind")
    if health.get("correctness_aggregates_computed") is not False:
        raise ValueError("qualification health contains outcome aggregation")


def _scale(value: float, denominator: int, target: int) -> float:
    return float(value) * float(target) / float(denominator)


def compile_qualification_forecast(
    health: Dict[str, Any],
    scenarios: Mapping[str, int] = DEFAULT_SCENARIOS,
) -> Dict[str, Any]:
    """Project calls/tokens/wall time without reading any outcome label."""

    _verify_health(health)
    if not scenarios:
        raise ValueError("at least one forecast scenario is required")
    normalized: Dict[str, int] = {}
    for name, tasks in scenarios.items():
        label = str(name).strip()
        if not label or not isinstance(tasks, int) or isinstance(tasks, bool) or tasks <= 0:
            raise ValueError("forecast scenarios require nonempty names and positive task counts")
        normalized[label] = tasks

    scenario_rows: Dict[str, Any] = {}
    for name, task_count in sorted(normalized.items()):
        systems: Dict[str, Any] = {}
        total_requests = 0.0
        total_reserved_tokens = 0.0
        total_observed_adjusted_tokens = 0.0
        observed_complete = True
        total_wall = 0.0
        for system_id in SYSTEM_IDS:
            source = health["systems"][system_id]
            episodes = int(source["attempted_episodes"])
            if episodes <= 0:
                raise ValueError("cannot forecast a system with zero attempted Q episodes")
            request_count = int(source["request_count"])
            usage_count = int(source["observed_usage_request_count"])
            observed_tokens = int(source["observed_total_tokens"])
            projected_requests = _scale(request_count, episodes, task_count)
            projected_reserved = _scale(int(source["reserved_token_upper"]), episodes, task_count)
            projected_wall = _scale(
                float(source["summed_episode_wall_time_s"]), episodes, task_count
            )
            if usage_count > 0:
                mean_tokens_per_measured_request = observed_tokens / usage_count
                projected_observed_adjusted = mean_tokens_per_measured_request * projected_requests
            else:
                projected_observed_adjusted = None
                observed_complete = False
            systems[system_id] = {
                "projected_episodes": task_count,
                "projected_request_count": projected_requests,
                "projected_reserved_token_upper": projected_reserved,
                "projected_observed_token_point": projected_observed_adjusted,
                "observed_usage_fraction": source["observed_usage_fraction"],
                "projected_summed_wall_time_s": projected_wall,
                "projected_summed_wall_time_h": projected_wall / 3600.0,
            }
            total_requests += projected_requests
            total_reserved_tokens += projected_reserved
            total_wall += projected_wall
            if projected_observed_adjusted is not None:
                total_observed_adjusted_tokens += projected_observed_adjusted
        scenario_rows[name] = {
            "task_count": task_count,
            "total_system_episodes": task_count * len(SYSTEM_IDS),
            "systems": systems,
            "totals": {
                "projected_request_count": total_requests,
                "projected_reserved_token_upper": total_reserved_tokens,
                "projected_observed_token_point": (
                    total_observed_adjusted_tokens if observed_complete else None
                ),
                "projected_summed_wall_time_s": total_wall,
                "projected_summed_wall_time_h": total_wall / 3600.0,
            },
        }

    forecast = {
        "format": FORECAST_FORMAT,
        "authorization_id": health["authorization_id"],
        "qualification_health_sha256": health["health_sha256"],
        "outcome_blind": True,
        "correctness_aggregates_computed": False,
        "basis": {
            "registered_qualification_tasks": 50,
            "attempted_episodes": health["totals"]["attempted_episodes"],
            "complete_full_trace_episodes": health["totals"]["complete_full_trace_episodes"],
            "linear_extrapolation": True,
        },
        "scenarios": scenario_rows,
        "interpretation_constraints": [
            "Forecasts assume the same stratum mix, harness policy, model, service regime and linear scaling as Q.",
            "Reserved-token projections are hard conservative upper bounds, not expected consumption.",
            "Observed-token point projections adjust for missing usage records and require the displayed coverage fraction.",
            "No scenario is authorized by this forecast; the owner must issue a separate hard-cap authorization.",
            "No correctness, dependence, repair/harm, utilization or ranking statistic was read or computed.",
        ],
    }
    forecast["forecast_sha256"] = sha256_json(forecast)
    return forecast


def write_qualification_forecast(
    health_path: Path,
    output_path: Path,
    scenarios: Mapping[str, int] = DEFAULT_SCENARIOS,
) -> Dict[str, Any]:
    if output_path.exists():
        raise FileExistsError("qualification forecast output already exists")
    health = json.loads(health_path.read_text(encoding="utf-8"))
    if not isinstance(health, dict):
        raise ValueError("qualification health must be a JSON object")
    forecast = compile_qualification_forecast(health, scenarios)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(forecast, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return forecast
