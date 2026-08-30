import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from mathaudit.hashing import sha256_json
from mathaudit.qualification_forecast import (
    compile_qualification_forecast,
    write_qualification_forecast,
)


def _health():
    systems = {}
    for index, system_id in enumerate(("mathrouter", "icma", "mathgoal"), start=1):
        systems[system_id] = {
            "attempted_episodes": 50,
            "request_count": 50 * index,
            "observed_usage_request_count": 25 * index,
            "observed_total_tokens": 2500 * index,
            "observed_usage_fraction": 0.5,
            "reserved_token_upper": 10000 * index,
            "summed_episode_wall_time_s": 500.0 * index,
        }
    health = {
        "format": "mathaudit-qualification-health-v0.1",
        "authorization_id": "fixture-q",
        "outcome_blind": True,
        "correctness_aggregates_computed": False,
        "totals": {
            "attempted_episodes": 150,
            "complete_full_trace_episodes": 147,
        },
        "systems": systems,
    }
    health["health_sha256"] = sha256_json(health)
    return health


def test_forecast_scales_and_usage_adjusts_without_outcomes(tmp_path):
    health = _health()
    forecast = compile_qualification_forecast(health, {"M": 200, "L": 1000})

    assert forecast["outcome_blind"] is True
    assert forecast["correctness_aggregates_computed"] is False
    assert forecast["scenarios"]["M"]["total_system_episodes"] == 600
    assert forecast["scenarios"]["M"]["totals"]["projected_request_count"] == 1200
    assert (
        forecast["scenarios"]["M"]["systems"]["mathrouter"][
            "projected_observed_token_point"
        ]
        == 20000
    )
    assert forecast["scenarios"]["L"]["totals"]["projected_reserved_token_upper"] == 1200000
    assert forecast["scenarios"]["L"]["totals"]["projected_summed_wall_time_s"] == 60000

    health_path = tmp_path / "health.json"
    output_path = tmp_path / "forecast.json"
    health_path.write_text(json.dumps(health), encoding="utf-8")
    written = write_qualification_forecast(health_path, output_path, {"M": 200})
    assert written == json.loads(output_path.read_text(encoding="utf-8"))

    schema_path = Path(__file__).parents[1] / (
        "schemas/mathaudit-qualification-forecast-v0.1.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert list(Draft202012Validator(schema).iter_errors(written)) == []


def test_forecast_rejects_tampered_health_hash():
    health = _health()
    tampered = copy.deepcopy(health)
    tampered["systems"]["mathrouter"]["request_count"] += 1
    with pytest.raises(ValueError, match="self-hash mismatch"):
        compile_qualification_forecast(tampered)
