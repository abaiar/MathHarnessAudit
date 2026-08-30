# SPDX-License-Identifier: MIT

"""Fail-closed, prompt-free budget accounting for qualification requests."""

from __future__ import annotations

import copy
from decimal import Decimal
from typing import Any, Dict, Optional

from .hashing import sha256_json
from .qualification import verify_qualification_authorization

LEDGER_FORMAT = "mathaudit-qualification-budget-ledger-v0.1"
INPUT_TOKEN_OVERHEAD_RESERVE = 4096


def _with_hash(payload: Dict[str, Any]) -> Dict[str, Any]:
    result = copy.deepcopy(payload)
    result.pop("ledger_sha256", None)
    result["ledger_sha256"] = sha256_json(result)
    return result


def _verify_hash(ledger: Dict[str, Any]) -> None:
    claimed = ledger.get("ledger_sha256")
    without_hash = copy.deepcopy(ledger)
    without_hash.pop("ledger_sha256", None)
    if claimed != sha256_json(without_hash):
        raise ValueError("budget ledger self-hash mismatch")


def _money(value: Any) -> Decimal:
    return Decimal(str(value))


def _money_text(value: Decimal) -> str:
    normalized = value.quantize(Decimal("0.000000001"))
    return format(normalized, "f")


def initialize_budget_ledger(authorization: Dict[str, Any]) -> Dict[str, Any]:
    """Create an empty ledger only from a semantically runnable authorization."""

    verify_qualification_authorization(authorization)
    systems = {
        item["system_id"]: {
            "request_count": 0,
            "observed_usage_request_count": 0,
            "observed_input_tokens": 0,
            "observed_output_tokens": 0,
            "observed_total_tokens": 0,
            "reserved_input_token_upper": 0,
            "reserved_output_token_upper": 0,
            "reserved_token_upper": 0,
            "reserved_monetary_cny": "0.000000000",
            "summed_episode_wall_time_s": 0.0,
        }
        for item in authorization["systems"]
    }
    ledger = {
        "format": LEDGER_FORMAT,
        "authorization_id": authorization["authorization_id"],
        "currency": authorization["total_budget"]["currency"],
        "accounting_mode": authorization["monetary_accounting"]["mode"],
        "input_token_overhead_reserve": INPUT_TOKEN_OVERHEAD_RESERVE,
        "totals": {
            "request_count": 0,
            "observed_usage_request_count": 0,
            "observed_input_tokens": 0,
            "observed_output_tokens": 0,
            "observed_total_tokens": 0,
            "reserved_input_token_upper": 0,
            "reserved_output_token_upper": 0,
            "reserved_token_upper": 0,
            "reserved_monetary_cny": "0.000000000",
            "summed_episode_wall_time_s": 0.0,
        },
        "systems": systems,
        "requests": [],
        "episodes": [],
        "contains_prompt_or_response_text": False,
    }
    return _with_hash(ledger)


def verify_budget_ledger(
    ledger: Dict[str, Any], authorization: Dict[str, Any]
) -> Dict[str, Any]:
    """Verify self-hash, internal sums, authorization identity, and hard caps."""

    verify_qualification_authorization(authorization)
    _verify_hash(ledger)
    if ledger.get("format") != LEDGER_FORMAT:
        raise ValueError("unsupported budget ledger format")
    if ledger.get("authorization_id") != authorization["authorization_id"]:
        raise ValueError("budget ledger authorization mismatch")
    if ledger.get("currency") != authorization["total_budget"]["currency"]:
        raise ValueError("budget ledger currency mismatch")
    if ledger.get("accounting_mode") != authorization["monetary_accounting"]["mode"]:
        raise ValueError("budget ledger accounting-mode mismatch")
    if ledger.get("contains_prompt_or_response_text") is not False:
        raise ValueError("budget ledger text policy violation")

    requests = ledger.get("requests")
    episodes = ledger.get("episodes")
    systems = ledger.get("systems")
    if not isinstance(requests, list) or not isinstance(episodes, list) or not isinstance(systems, dict):
        raise ValueError("budget ledger collections are malformed")
    expected_ids = {item["system_id"] for item in authorization["systems"]}
    if set(systems) != expected_ids:
        raise ValueError("budget ledger system set mismatch")

    for system_id in sorted(expected_ids):
        request_rows = [item for item in requests if item.get("system_id") == system_id]
        episode_rows = [item for item in episodes if item.get("system_id") == system_id]
        totals = systems[system_id]
        if totals.get("request_count") != len(request_rows):
            raise ValueError("budget ledger request-count mismatch")
        usage_rows = [
            item for item in request_rows if "observed_total_tokens" in item
        ]
        if totals.get("observed_usage_request_count") != len(usage_rows):
            raise ValueError("budget ledger observed-usage-count mismatch")
        for field in (
            "observed_input_tokens",
            "observed_output_tokens",
            "observed_total_tokens",
        ):
            if totals.get(field) != sum(int(item[field]) for item in usage_rows):
                raise ValueError("budget ledger observed token sum mismatch")
        for field in (
            "reserved_input_token_upper",
            "reserved_output_token_upper",
            "reserved_token_upper",
        ):
            if totals.get(field) != sum(int(item[field]) for item in request_rows):
                raise ValueError("budget ledger token sum mismatch")
        expected_money = sum(
            (_money(item["reserved_monetary_cny"]) for item in request_rows),
            Decimal("0"),
        )
        if _money(totals.get("reserved_monetary_cny")) != expected_money:
            raise ValueError("budget ledger monetary sum mismatch")
        expected_wall = sum(float(item["wall_time_s"]) for item in episode_rows)
        if abs(float(totals.get("summed_episode_wall_time_s")) - expected_wall) > 1e-9:
            raise ValueError("budget ledger wall-time sum mismatch")
        system_auth = _system_authorization(authorization, system_id)
        if len(episode_rows) > system_auth["episode_cap"]:
            raise ValueError("budget ledger exceeds system episode cap")
        if totals["reserved_token_upper"] > system_auth["token_cap"]:
            raise ValueError("budget ledger exceeds system token cap")
        if expected_money > _money(system_auth["monetary_cap"]):
            raise ValueError("budget ledger exceeds system monetary cap")
        if expected_wall > system_auth["summed_wall_time_cap_s"]:
            raise ValueError("budget ledger exceeds system wall-time cap")

    total = ledger.get("totals")
    if not isinstance(total, dict):
        raise ValueError("budget ledger totals are malformed")
    if total.get("request_count") != len(requests):
        raise ValueError("budget ledger total request-count mismatch")
    total_usage_rows = [item for item in requests if "observed_total_tokens" in item]
    if total.get("observed_usage_request_count") != len(total_usage_rows):
        raise ValueError("budget ledger total observed-usage-count mismatch")
    for field in (
        "observed_input_tokens",
        "observed_output_tokens",
        "observed_total_tokens",
    ):
        if total.get(field) != sum(int(item[field]) for item in total_usage_rows):
            raise ValueError("budget ledger total observed token sum mismatch")
    for field in (
        "reserved_input_token_upper",
        "reserved_output_token_upper",
        "reserved_token_upper",
    ):
        if total.get(field) != sum(int(item[field]) for item in requests):
            raise ValueError("budget ledger total token sum mismatch")
    total_money = sum(
        (_money(item["reserved_monetary_cny"]) for item in requests), Decimal("0")
    )
    total_wall = sum(float(item["wall_time_s"]) for item in episodes)
    if len(episodes) > authorization["total_budget"]["episode_cap"]:
        raise ValueError("budget ledger exceeds total episode cap")
    if _money(total.get("reserved_monetary_cny")) != total_money:
        raise ValueError("budget ledger total monetary sum mismatch")
    if abs(float(total.get("summed_episode_wall_time_s")) - total_wall) > 1e-9:
        raise ValueError("budget ledger total wall-time sum mismatch")
    if total["reserved_token_upper"] > authorization["total_budget"]["token_cap"]:
        raise ValueError("budget ledger exceeds total token cap")
    if total_money > _money(authorization["total_budget"]["monetary_cap"]):
        raise ValueError("budget ledger exceeds total monetary cap")
    if total_wall > authorization["total_budget"]["summed_wall_time_cap_s"]:
        raise ValueError("budget ledger exceeds total wall-time cap")
    return {
        "authorization_id": ledger["authorization_id"],
        "request_count": len(requests),
        "episode_count": len(episodes),
        "observed_usage_request_count": total["observed_usage_request_count"],
        "observed_input_tokens": total["observed_input_tokens"],
        "observed_output_tokens": total["observed_output_tokens"],
        "observed_total_tokens": total["observed_total_tokens"],
        "reserved_token_upper": total["reserved_token_upper"],
        "reserved_monetary_cny": total["reserved_monetary_cny"],
        "summed_episode_wall_time_s": total["summed_episode_wall_time_s"],
        "ledger_sha256": ledger["ledger_sha256"],
    }


def _system_authorization(
    authorization: Dict[str, Any], system_id: str
) -> Dict[str, Any]:
    matches = [
        item for item in authorization["systems"] if item.get("system_id") == system_id
    ]
    if len(matches) != 1:
        raise ValueError("system is not uniquely authorized: %s" % system_id)
    return matches[0]


def _request_reservation(
    request_body: bytes,
    request_payload: Dict[str, Any],
    system_authorization: Dict[str, Any],
    monetary_accounting: Dict[str, Any],
) -> Dict[str, Any]:
    if request_payload.get("model") != system_authorization["model"]:
        raise ValueError("request model differs from authorization")
    max_tokens = request_payload.get("max_tokens")
    if (
        not isinstance(max_tokens, int)
        or isinstance(max_tokens, bool)
        or max_tokens <= 0
        or max_tokens > system_authorization["max_output_tokens"]
    ):
        raise ValueError("request max_tokens is missing or exceeds authorization")
    if request_payload.get("stream") not in (None, False):
        raise ValueError("qualification budget gateway requires non-streaming requests")

    input_upper = len(request_body) + INPUT_TOKEN_OVERHEAD_RESERVE
    output_upper = max_tokens
    token_upper = input_upper + output_upper
    if monetary_accounting["mode"] == "free_quota":
        monetary_upper = Decimal("0")
    else:
        input_rate = _money(monetary_accounting["input_cny_per_million_tokens"])
        output_rate = _money(monetary_accounting["output_cny_per_million_tokens"])
        monetary_upper = (
            Decimal(input_upper) * input_rate + Decimal(output_upper) * output_rate
        ) / Decimal(1_000_000)
    return {
        "request_body_bytes": len(request_body),
        "reserved_input_token_upper": input_upper,
        "reserved_output_token_upper": output_upper,
        "reserved_token_upper": token_upper,
        "reserved_monetary_cny": monetary_upper,
    }


def reserve_request(
    ledger: Dict[str, Any],
    authorization: Dict[str, Any],
    *,
    system_id: str,
    request_id: str,
    requested_at: str,
    request_body: bytes,
    request_payload: Dict[str, Any],
) -> Dict[str, Any]:
    """Reserve conservative token/money upper bounds before an HTTP request."""

    verify_qualification_authorization(authorization)
    _verify_hash(ledger)
    if ledger.get("format") != LEDGER_FORMAT:
        raise ValueError("unsupported budget ledger format")
    if ledger.get("authorization_id") != authorization["authorization_id"]:
        raise ValueError("budget ledger authorization mismatch")
    if not request_id or any(item["request_id"] == request_id for item in ledger["requests"]):
        raise ValueError("request_id must be nonempty and unique")

    system_auth = _system_authorization(authorization, system_id)
    reservation = _request_reservation(
        request_body,
        request_payload,
        system_auth,
        authorization["monetary_accounting"],
    )
    updated = copy.deepcopy(ledger)
    updated.pop("ledger_sha256", None)
    system_totals = updated["systems"][system_id]
    total_totals = updated["totals"]
    new_system_tokens = system_totals["reserved_token_upper"] + reservation[
        "reserved_token_upper"
    ]
    new_total_tokens = total_totals["reserved_token_upper"] + reservation[
        "reserved_token_upper"
    ]
    if new_system_tokens > system_auth["token_cap"]:
        raise ValueError("system token hard cap would be exceeded")
    if new_total_tokens > authorization["total_budget"]["token_cap"]:
        raise ValueError("total token hard cap would be exceeded")

    system_money = _money(system_totals["reserved_monetary_cny"]) + reservation[
        "reserved_monetary_cny"
    ]
    total_money = _money(total_totals["reserved_monetary_cny"]) + reservation[
        "reserved_monetary_cny"
    ]
    if system_money > _money(system_auth["monetary_cap"]):
        raise ValueError("system monetary hard cap would be exceeded")
    if total_money > _money(authorization["total_budget"]["monetary_cap"]):
        raise ValueError("total monetary hard cap would be exceeded")

    for target in (system_totals, total_totals):
        target["request_count"] += 1
        for key in (
            "reserved_input_token_upper",
            "reserved_output_token_upper",
            "reserved_token_upper",
        ):
            target[key] += reservation[key]
    system_totals["reserved_monetary_cny"] = _money_text(system_money)
    total_totals["reserved_monetary_cny"] = _money_text(total_money)
    updated["requests"].append(
        {
            "request_id": request_id,
            "system_id": system_id,
            "requested_at": requested_at,
            "model": request_payload["model"],
            "max_tokens": request_payload["max_tokens"],
            "request_body_bytes": reservation["request_body_bytes"],
            "reserved_input_token_upper": reservation["reserved_input_token_upper"],
            "reserved_output_token_upper": reservation["reserved_output_token_upper"],
            "reserved_token_upper": reservation["reserved_token_upper"],
            "reserved_monetary_cny": _money_text(
                reservation["reserved_monetary_cny"]
            ),
            "status": "reserved",
        }
    )
    return _with_hash(updated)


def finalize_request(
    ledger: Dict[str, Any],
    *,
    request_id: str,
    status: str,
    http_status: Optional[int] = None,
    provider_request_id: Optional[str] = None,
    observed_usage: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    """Finalize one reservation without refunding its conservative upper bound."""

    _verify_hash(ledger)
    allowed = {"completed", "transport_failed", "provider_error"}
    if status not in allowed:
        raise ValueError("unsupported finalized request status")
    updated = copy.deepcopy(ledger)
    updated.pop("ledger_sha256", None)
    matches = [item for item in updated["requests"] if item["request_id"] == request_id]
    if len(matches) != 1:
        raise ValueError("request reservation is missing or duplicated")
    request = matches[0]
    if request["status"] != "reserved":
        raise ValueError("request reservation is already finalized")
    if http_status is not None and (
        not isinstance(http_status, int)
        or isinstance(http_status, bool)
        or not 100 <= http_status <= 599
    ):
        raise ValueError("http_status must be a valid HTTP status")
    request["status"] = status
    if http_status is not None:
        request["http_status"] = http_status
    if provider_request_id:
        request["provider_request_id"] = str(provider_request_id)[:256]
    if observed_usage is not None:
        if status != "completed":
            raise ValueError("observed usage may be recorded only for a completed request")
        required = {
            "observed_input_tokens",
            "observed_output_tokens",
            "observed_total_tokens",
        }
        if set(observed_usage) != required:
            raise ValueError("observed usage fields are incomplete")
        for field in sorted(required):
            value = observed_usage[field]
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError("observed token usage must be nonnegative integers")
        if observed_usage["observed_total_tokens"] < (
            observed_usage["observed_input_tokens"]
            + observed_usage["observed_output_tokens"]
        ):
            raise ValueError("observed total tokens are smaller than input plus output")
        request.update(observed_usage)
        for target in (updated["systems"][request["system_id"]], updated["totals"]):
            target["observed_usage_request_count"] += 1
            for field in required:
                target[field] += observed_usage[field]
    return _with_hash(updated)


def record_episode_wall_time(
    ledger: Dict[str, Any],
    authorization: Dict[str, Any],
    *,
    system_id: str,
    episode_id: str,
    wall_time_s: float,
    status: str,
) -> Dict[str, Any]:
    """Append one episode duration and enforce episode-count plus wall caps."""

    verify_qualification_authorization(authorization)
    _verify_hash(ledger)
    if not isinstance(wall_time_s, (int, float)) or isinstance(wall_time_s, bool) or wall_time_s < 0:
        raise ValueError("episode wall_time_s must be nonnegative")
    if not episode_id or any(item["episode_id"] == episode_id for item in ledger["episodes"]):
        raise ValueError("episode_id must be nonempty and unique")
    system_auth = _system_authorization(authorization, system_id)
    system_episode_count = sum(
        item.get("system_id") == system_id for item in ledger["episodes"]
    )
    if system_episode_count + 1 > system_auth["episode_cap"]:
        raise ValueError("system episode hard cap would be exceeded")
    if len(ledger["episodes"]) + 1 > authorization["total_budget"]["episode_cap"]:
        raise ValueError("total episode hard cap would be exceeded")
    updated = copy.deepcopy(ledger)
    updated.pop("ledger_sha256", None)
    system_totals = updated["systems"][system_id]
    total_totals = updated["totals"]
    new_system_wall = system_totals["summed_episode_wall_time_s"] + float(wall_time_s)
    new_total_wall = total_totals["summed_episode_wall_time_s"] + float(wall_time_s)
    if new_system_wall > system_auth["summed_wall_time_cap_s"]:
        raise ValueError("system wall-time hard cap would be exceeded")
    if new_total_wall > authorization["total_budget"]["summed_wall_time_cap_s"]:
        raise ValueError("total wall-time hard cap would be exceeded")
    system_totals["summed_episode_wall_time_s"] = new_system_wall
    total_totals["summed_episode_wall_time_s"] = new_total_wall
    updated["episodes"].append(
        {
            "episode_id": episode_id,
            "system_id": system_id,
            "wall_time_s": float(wall_time_s),
            "status": status,
        }
    )
    return _with_hash(updated)
