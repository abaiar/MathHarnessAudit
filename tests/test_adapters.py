# SPDX-License-Identifier: MIT

import json
from pathlib import Path

from mathaudit.adapters import (
    ICMAAdapter,
    MathGoalAdapter,
    MathRouterAdapter,
    OTelAdapter,
    RunContext,
)
from mathaudit.ingest import load_problem_manifest
from mathaudit.validation import validate_episode

FIXTURES = Path(__file__).parents[1] / "examples" / "fixtures"


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def contexts():
    return load_problem_manifest(
        FIXTURES / "problems.jsonl",
        dataset_id="fixture",
        split="test",
        stratum="easy",
    )


def run_context(system_id):
    return RunContext(
        run_id="fixture-run",
        system_id=system_id,
        system_name=system_id,
        system_version="fixture",
    )


def test_icma_fixture_converts_without_semantic_issues():
    adapter = ICMAAdapter()
    episode = adapter.convert(load_json(FIXTURES / "icma" / "0.json"), contexts()["0"], run_context("icma"))
    assert validate_episode(episode) == []
    assert episode.adapter.fidelity.value == "B"
    assert len(episode.evidence) == 4


def test_mathrouter_fixture_preserves_selection():
    adapter = MathRouterAdapter()
    episode = adapter.convert(load_json(FIXTURES / "mathrouter" / "1.json"), contexts()["1"], run_context("mathrouter"))
    assert validate_episode(episode) == []
    assert any(decision.selected_evidence_ids for decision in episode.decisions)


def test_mathgoal_full_fixture_is_fidelity_a():
    adapter = MathGoalAdapter()
    episode = adapter.convert(load_json(FIXTURES / "mathgoal_full.json"), contexts()["2"], run_context("mathgoal"))
    assert validate_episode(episode) == []
    assert episode.adapter.fidelity.value == "A"
    assert len(episode.sources) >= 4
    assert any(item.kind.value == "tool_result" for item in episode.evidence)
    assert {item.source_id for item in episode.sources}.issuperset(
        {
            "candidate_role:rigorous",
            "candidate_role:alternative",
            "tool_role:rigorous",
            "tool_role:alternative",
        }
    )
    alternative_tool = next(
        item
        for item in episode.source_observations
        if item.source_id == "tool_role:alternative"
    )
    assert alternative_tool.invocation.value == "not_called"
    assert alternative_tool.outcome.value == "not_observable"


def test_mathgoal_tool_corrected_candidate_reuses_original_tool_provenance():
    adapter = MathGoalAdapter()
    payload = load_json(FIXTURES / "mathgoal_full.json")
    corrected = dict(payload["candidates"][0])
    corrected.update({"id": "c1_tool", "agent_role": "tool_corrected", "answer": "2"})
    payload["candidates"].append(corrected)
    episode = adapter.convert(payload, contexts()["2"], run_context("mathgoal"))
    tool_sources = [item for item in episode.sources if item.source_type.value == "python"]
    assert {item.source_id for item in tool_sources} == {
        "tool_role:rigorous",
        "tool_role:alternative",
    }
    corrected_source = next(
        item.source_id for item in episode.sources if item.role == "tool_corrected"
    )
    corrected_evidence = next(
        item.evidence_id
        for item in episode.evidence
        if item.observation_id == "observation:%s" % corrected_source
    )
    parents = {
        edge.from_id for edge in episode.provenance_edges if edge.to_id == corrected_evidence
    }
    assert "evidence:candidate_role:rigorous" in parents
    assert "evidence:tool_role:rigorous" in parents
    assert validate_episode(episode) == []


def test_otel_bridge_requires_explicit_final_marker():
    adapter = OTelAdapter()
    episode = adapter.convert(load_json(FIXTURES / "otel.json"), contexts()["2"], run_context("otel"))
    assert validate_episode(episode) == []
    assert episode.final_output.status.value == "produced"
    assert episode.final_output.evidence_id == "evidence:otel:span-final"
    assert len(episode.provenance_edges) == 1
