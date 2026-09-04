# SPDX-License-Identifier: MIT

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from mathaudit.budget import (
    INPUT_TOKEN_OVERHEAD_RESERVE,
    finalize_request,
    initialize_budget_ledger,
    record_episode_wall_time,
    reserve_request,
    verify_budget_ledger,
)


def _authorization(mode="free_quota"):
    systems = []
    for system_id in ("mathrouter", "icma", "mathgoal"):
        systems.append(
            {
                "system_id": system_id,
                "provider": "fixture",
                "model": "fixture-model",
                "model_revision": "fixture-revision",
                "endpoint_class": "fixture",
                "endpoint_url": "https://example.invalid/v1/chat/completions",
                "endpoint_available": True,
                "parameters": {},
                "concurrency": 1,
                "episode_timeout_s": 1200,
                "max_output_tokens": 8192,
                "retry_policy": "transport only",
                "retry_control": {
                    "max_retries": 1,
                    "eligible_failure_class": "pre_response_transport_failure_only",
                    "forbid_after_any_response": True,
                    "forbid_on_parse_failure": True,
                    "forbid_on_tool_failure": True,
                },
                "episode_cap": 50,
                "token_cap": 100000,
                "currency": "CNY",
                "monetary_cap": 3,
                "summed_wall_time_cap_s": 50000,
            }
        )
    accounting = {
        "mode": mode,
        "free_quota_confirmed": mode == "free_quota",
        "input_cny_per_million_tokens": None if mode == "free_quota" else 2,
        "output_cny_per_million_tokens": None if mode == "free_quota" else 8,
        "evidence_source": "fixture evidence",
    }
    return {
        "format": "mathaudit-compute-authorization-v0.1",
        "authorization_id": "fixture-q",
        "status": "authorized",
        "scope": "qualification_q",
        "authorized_by": "owner",
        "authorized_at": "2026-08-23T00:00:00Z",
        "total_budget": {
            "episode_cap": 150,
            "token_cap": 300000,
            "currency": "CNY",
            "monetary_cap": 10,
            "summed_wall_time_cap_s": 150000,
        },
        "monetary_accounting": accounting,
        "stop_policy": {
            "quota_or_transport_failure_rate": 0.05,
            "stop_on_task_dependent_missingness": True,
            "stop_on_trace_loss": True,
        },
        "systems": systems,
        "secrets_recorded": False,
        "notes": [],
    }


def _request(max_tokens=1000, model="fixture-model"):
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "private prompt"}],
        "max_tokens": max_tokens,
        "stream": False,
    }
    return json.dumps(payload).encode(), payload


def test_free_quota_request_reserves_conservative_tokens_without_text():
    authorization = _authorization()
    ledger = initialize_budget_ledger(authorization)
    body, payload = _request()
    updated = reserve_request(
        ledger,
        authorization,
        system_id="mathrouter",
        request_id="request-1",
        requested_at="2026-08-23T00:00:01Z",
        request_body=body,
        request_payload=payload,
    )
    request = updated["requests"][0]
    assert request["reserved_input_token_upper"] == len(body) + INPUT_TOKEN_OVERHEAD_RESERVE
    assert request["reserved_output_token_upper"] == 1000
    assert updated["totals"]["reserved_monetary_cny"] == "0.000000000"
    assert "private prompt" not in json.dumps(updated)
    assert ledger["totals"]["request_count"] == 0
    assert verify_budget_ledger(updated, authorization)["request_count"] == 1


def test_empty_and_reserved_ledgers_validate_against_public_schema():
    schema_path = (
        Path(__file__).resolve().parents[1]
        / "schemas"
        / "mathaudit-qualification-budget-ledger-v0.1.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    authorization = _authorization()
    ledger = initialize_budget_ledger(authorization)
    body, payload = _request()
    reserved = reserve_request(
        ledger,
        authorization,
        system_id="mathrouter",
        request_id="request-1",
        requested_at="2026-08-23T00:00:01Z",
        request_body=body,
        request_payload=payload,
    )
    validator = Draft202012Validator(schema)
    assert list(validator.iter_errors(ledger)) == []
    assert list(validator.iter_errors(reserved)) == []


def test_request_model_output_cap_and_duplicate_id_are_fail_closed():
    authorization = _authorization()
    ledger = initialize_budget_ledger(authorization)
    body, payload = _request(model="wrong")
    with pytest.raises(ValueError, match="model differs"):
        reserve_request(
            ledger,
            authorization,
            system_id="icma",
            request_id="request-1",
            requested_at="now",
            request_body=body,
            request_payload=payload,
        )


def test_request_finalization_is_one_way_and_keeps_reservation():
    authorization = _authorization()
    ledger = initialize_budget_ledger(authorization)
    body, payload = _request()
    reserved = reserve_request(
        ledger,
        authorization,
        system_id="icma",
        request_id="request-1",
        requested_at="now",
        request_body=body,
        request_payload=payload,
    )
    finalized = finalize_request(
        reserved,
        request_id="request-1",
        status="completed",
        http_status=200,
        provider_request_id="provider-1",
        observed_usage={
            "observed_input_tokens": 20,
            "observed_output_tokens": 5,
            "observed_total_tokens": 25,
        },
    )
    assert finalized["requests"][0]["status"] == "completed"
    assert finalized["totals"]["reserved_token_upper"] == reserved["totals"]["reserved_token_upper"]
    assert finalized["totals"]["observed_usage_request_count"] == 1
    assert finalized["totals"]["observed_total_tokens"] == 25
    with pytest.raises(ValueError, match="already finalized"):
        finalize_request(finalized, request_id="request-1", status="completed")
    body, payload = _request(max_tokens=9000)
    with pytest.raises(ValueError, match="max_tokens"):
        reserve_request(
            ledger,
            authorization,
            system_id="icma",
            request_id="request-1",
            requested_at="now",
            request_body=body,
            request_payload=payload,
        )

    body, payload = _request()
    ledger = reserve_request(
        ledger,
        authorization,
        system_id="icma",
        request_id="request-1",
        requested_at="now",
        request_body=body,
        request_payload=payload,
    )
    with pytest.raises(ValueError, match="unique"):
        reserve_request(
            ledger,
            authorization,
            system_id="icma",
            request_id="request-1",
            requested_at="now",
            request_body=body,
            request_payload=payload,
        )


def test_token_tariff_and_hard_caps_are_enforced_before_mutation():
    authorization = _authorization(mode="token_tariff")
    ledger = initialize_budget_ledger(authorization)
    body, payload = _request(max_tokens=8000)
    updated = reserve_request(
        ledger,
        authorization,
        system_id="mathgoal",
        request_id="request-1",
        requested_at="now",
        request_body=body,
        request_payload=payload,
    )
    assert float(updated["totals"]["reserved_monetary_cny"]) > 0

    tiny = copy.deepcopy(authorization)
    tiny["systems"][2]["token_cap"] = 1
    tiny["total_budget"]["token_cap"] = 200001
    tiny["systems"][0]["token_cap"] = 100000
    tiny["systems"][1]["token_cap"] = 100000
    tiny_ledger = initialize_budget_ledger(tiny)
    with pytest.raises(ValueError, match="system token hard cap"):
        reserve_request(
            tiny_ledger,
            tiny,
            system_id="mathgoal",
            request_id="request-1",
            requested_at="now",
            request_body=body,
            request_payload=payload,
        )


def test_episode_wall_time_is_append_only_and_cap_checked():
    authorization = _authorization()
    ledger = initialize_budget_ledger(authorization)
    updated = record_episode_wall_time(
        ledger,
        authorization,
        system_id="mathrouter",
        episode_id="episode-1",
        wall_time_s=12.5,
        status="completed",
    )
    assert updated["totals"]["summed_episode_wall_time_s"] == 12.5
    assert verify_budget_ledger(updated, authorization)["episode_count"] == 1
    with pytest.raises(ValueError, match="unique"):
        record_episode_wall_time(
            updated,
            authorization,
            system_id="mathrouter",
            episode_id="episode-1",
            wall_time_s=1,
            status="completed",
        )
    capped = updated
    for number in range(2, 51):
        capped = record_episode_wall_time(
            capped,
            authorization,
            system_id="mathrouter",
            episode_id="episode-%d" % number,
            wall_time_s=0,
            status="completed",
        )
    with pytest.raises(ValueError, match="system episode hard cap"):
        record_episode_wall_time(
            capped,
            authorization,
            system_id="mathrouter",
            episode_id="episode-51",
            wall_time_s=0,
            status="completed",
        )
