# SPDX-License-Identifier: MIT

import copy
import csv
import hashlib
import json
import shutil
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from mathaudit.adjudication import (
    RATER_FIELDS,
    agreement_and_conflicts,
    apply_adjudication,
    export_adjudication_bundle,
)
from mathaudit.hashing import sha256_json
from mathaudit.io import read_episodes, write_episodes
from mathaudit.qualification_analysis import build_qualification_analysis
from mathaudit.qualification_composite import (
    assemble_qualification_composite,
    assemble_qualification_lineage_composite,
    assemble_qualification_replacement_composite,
)
from mathaudit.qualification_publication import (
    reproduce_and_compare_qualification_publication,
    verify_public_analysis_release,
    verify_qualification_publication_bundle,
    write_qualification_publication_bundle,
)
from mathaudit.qualification_scoring import (
    freeze_qualification_adjudication,
    prepare_qualification_adjudication,
    score_qualification_composite,
)


def _file_sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_plan():
    entries = []
    systems = ("mathrouter", "icma", "mathgoal")
    for task_position in range(50):
        for within_task_position, system_id in enumerate(systems):
            sequence = len(entries)
            entries.append(
                {
                    "sequence": sequence,
                    "task_position": task_position,
                    "within_task_position": within_task_position,
                    "idx": task_position,
                    "problem_id": "fixture#%d" % task_position,
                    "problem_sha256": "%064x" % (task_position + 1),
                    "stratum": "standard" if task_position < 25 else "hard_gt_5",
                    "system_id": system_id,
                    "episode_timeout_s": 1200,
                    "output_relative_path": "%s/%d.json" % (system_id, task_position),
                }
            )
    plan = {
        "format": "mathaudit-qualification-execution-plan-v0.1",
        "authorization_id": "fixture-prefix",
        "entries": entries,
    }
    plan["plan_sha256"] = sha256_json(plan)
    return plan


def _state(plan, restart=11):
    rows = [
        {"sequence": entry["sequence"], "status": "completed"}
        for entry in plan["entries"][:restart]
    ]
    rows.append({"sequence": restart, "status": "runner_or_provider_failure"})
    state = {
        "format": "mathaudit-qualification-executor-state-v0.3",
        "authorization_id": "fixture-prefix",
        "plan_sha256": plan["plan_sha256"],
        "status": "stopped_failure",
        "current_episodes": [],
        "episodes": rows,
    }
    state["state_sha256"] = sha256_json(state)
    return state


def _continuation_plan(source_plan, prefix_state, restart=11):
    plan = {
        "format": "mathaudit-qualification-execution-plan-v0.2",
        "authorization_id": "fixture-continuation",
        "continuation": {
            "source_plan_sha256": source_plan["plan_sha256"],
            "source_state_sha256": prefix_state["state_sha256"],
            "completed_prefix_episode_count": restart,
            "restart_sequence": restart,
        },
        "entries": copy.deepcopy(source_plan["entries"][restart:]),
    }
    plan["plan_sha256"] = sha256_json(plan)
    return plan


def _continuation_state(plan):
    state = {
        "format": "mathaudit-qualification-executor-state-v0.3",
        "authorization_id": "fixture-continuation",
        "plan_sha256": plan["plan_sha256"],
        "status": "completed",
        "current_episodes": [],
        "episodes": [
            {"sequence": entry["sequence"], "status": "completed"} for entry in plan["entries"]
        ],
    }
    state["state_sha256"] = sha256_json(state)
    return state


def _lineage_state(plan, completed_start, completed_end, failed_boundary=None):
    rows = []
    by_sequence = {entry["sequence"]: entry for entry in plan["entries"]}
    last = failed_boundary if failed_boundary is not None else completed_end
    for sequence in range(completed_start, last + 1):
        entry = by_sequence[sequence]
        completed = sequence <= completed_end
        rows.append(
            {
                "sequence": sequence,
                "system_id": entry["system_id"],
                "idx": entry["idx"],
                "status": "completed" if completed else "runner_or_provider_failure",
                "attempts": [{"valid_full_trace": completed}],
            }
        )
    state = {
        "format": "mathaudit-qualification-executor-state-v0.3",
        "authorization_id": plan["authorization_id"],
        "plan_sha256": plan["plan_sha256"],
        "status": "stopped_failure" if failed_boundary is not None else "completed",
        "current_episodes": [],
        "episodes": rows,
    }
    state["state_sha256"] = sha256_json(state)
    return state


def _lineage_continuation_plan(source_plan, source_state, restart, authorization_id):
    root_entries = [entry for entry in source_plan["entries"] if entry["sequence"] >= restart]
    plan = {
        "format": "mathaudit-qualification-execution-plan-v0.2",
        "authorization_id": authorization_id,
        "continuation": {
            "source_authorization_id": source_state["authorization_id"],
            "source_plan_sha256": source_plan["plan_sha256"],
            "source_state_sha256": source_state["state_sha256"],
            "source_closeout_sha256": "b" * 64,
            "completed_prefix_episode_count": restart,
            "restart_sequence": restart,
            "final_target_episode_count": 150,
        },
        "entries": copy.deepcopy(root_entries),
    }
    plan["plan_sha256"] = sha256_json(plan)
    return plan


def _episodes(entries, episode_factory, run_id):
    result = []
    for entry in entries:
        base = episode_factory(entry["sequence"], True, True, True)
        result.append(
            base.model_copy(
                update={
                    "episode_id": "%s:%d" % (run_id, entry["sequence"]),
                    "problem": base.problem.model_copy(
                        update={
                            "problem_id": entry["problem_id"],
                            "stratum": entry["stratum"],
                        }
                    ),
                    "system": base.system.model_copy(update={"system_id": entry["system_id"]}),
                    "run": base.run.model_copy(update={"run_id": run_id}),
                    "labels": [],
                }
            )
        )
    return result


def _write_closeout(root, authorization_id, plan_sha256, episodes):
    root.mkdir(parents=True)
    manifest_rows = []
    for system_id in ("mathrouter", "icma", "mathgoal"):
        system_episodes = [episode for episode in episodes if episode.system.system_id == system_id]
        canonical_path = root / system_id / "canonical.jsonl"
        write_episodes(canonical_path, system_episodes)
        run_manifest = {
            "artifacts": [
                {
                    "role": "canonical_episodes",
                    "relative_path": "%s/canonical.jsonl" % system_id,
                    "sha256": _file_sha256(canonical_path),
                    "records": len(system_episodes),
                    "private": True,
                }
            ]
        }
        run_path = root / system_id / "run-manifest.final.json"
        run_path.write_text(json.dumps(run_manifest), encoding="utf-8")
        manifest_rows.append(
            {
                "system_id": system_id,
                "relative_path": "%s/run-manifest.final.json" % system_id,
                "sha256": _file_sha256(run_path),
            }
        )
    health_path = root / "qualification-health.json"
    health_path.write_text("{}\n", encoding="utf-8")
    closeout = {
        "format": "mathaudit-qualification-closeout-v0.1",
        "authorization_id": authorization_id,
        "plan_sha256": plan_sha256,
        "outcome_blind": True,
        "health_report": {
            "relative_path": "qualification-health.json",
            "sha256": _file_sha256(health_path),
        },
        "final_run_manifests": manifest_rows,
        "contains_prompt_or_response_text": False,
    }
    closeout["closeout_sha256"] = sha256_json(closeout)
    (root / "closeout-manifest.json").write_text(json.dumps(closeout), encoding="utf-8")


def _complete_agreeing_rater(path, annotator):
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for index, row in enumerate(rows):
        row.update(
            {
                "annotator_id": annotator,
                "label": "correct",
                "confidence": "high",
                "reason_code": "exact",
                "rationale": "Independent fixture comparison.",
                "timestamp_utc": "2026-08-24T00:%02d:00Z" % (index % 60),
            }
        )
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RATER_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def test_composite_assembles_exact_150_outcome_blind_traces(tmp_path, episode_factory):
    source_plan = _source_plan()
    prefix_state = _state(source_plan)
    continuation_plan = _continuation_plan(source_plan, prefix_state)
    continuation_state = _continuation_state(continuation_plan)
    source_plan_path = tmp_path / "source-plan.json"
    prefix_state_path = tmp_path / "prefix-state.json"
    continuation_plan_path = tmp_path / "continuation-plan.json"
    continuation_state_path = tmp_path / "continuation-state.json"
    for path, payload in (
        (source_plan_path, source_plan),
        (prefix_state_path, prefix_state),
        (continuation_plan_path, continuation_plan),
        (continuation_state_path, continuation_state),
    ):
        path.write_text(json.dumps(payload), encoding="utf-8")

    prefix_entries = source_plan["entries"][:11]
    suffix_entries = continuation_plan["entries"]
    prefix_closeout = tmp_path / "prefix-closeout"
    continuation_closeout = tmp_path / "continuation-closeout"
    _write_closeout(
        prefix_closeout,
        "fixture-prefix",
        source_plan["plan_sha256"],
        _episodes(prefix_entries, episode_factory, "prefix"),
    )
    _write_closeout(
        continuation_closeout,
        "fixture-continuation",
        continuation_plan["plan_sha256"],
        _episodes(suffix_entries, episode_factory, "continuation"),
    )
    output = tmp_path / "composite"
    manifest = assemble_qualification_composite(
        source_plan_path=source_plan_path,
        prefix_state_path=prefix_state_path,
        continuation_plan_path=continuation_plan_path,
        continuation_state_path=continuation_state_path,
        prefix_closeout_dir=prefix_closeout,
        continuation_closeout_dir=continuation_closeout,
        output_dir=output,
    )
    assert manifest["episode_count"] == 150
    assert manifest["prefix"]["episode_count"] == 11
    assert manifest["continuation"]["episode_count"] == 139
    assert all(item["records"] == 50 for item in manifest["canonical_artifacts"])
    index = json.loads((output / "sequence-index.json").read_text(encoding="utf-8"))
    assert [row["sequence"] for row in index["records"]] == list(range(150))
    assert [row["source_role"] for row in index["records"][:11]] == ["prefix"] * 11
    schema = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "schemas/mathaudit-qualification-composite-v0.1.schema.json"
        ).read_text(encoding="utf-8")
    )
    assert list(Draft202012Validator(schema).iter_errors(manifest)) == []

    scoring_output = tmp_path / "scoring"
    scoring = score_qualification_composite(composite_dir=output, output_dir=scoring_output)
    assert scoring["episode_count"] == 150
    assert scoring["correctness_labels_computed"] is True
    assert sum(scoring["label_counts"].values()) > 150
    scoring_schema = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "schemas/mathaudit-qualification-scoring-v0.1.schema.json"
        ).read_text(encoding="utf-8")
    )
    assert list(Draft202012Validator(scoring_schema).iter_errors(scoring)) == []

    analysis_config = {
        "format": "mathaudit-qualification-analysis-config-v0.1",
        "source_plan_sha256": source_plan["plan_sha256"],
        "minimum_complete_cases": 20,
        "bootstrap_replicates": 0,
        "seed": 20260823,
        "expected_panel_episode_count": 25,
        "panels": [
            {
                "panel_id": "%s-%s" % (system_id, stratum),
                "system_id": system_id,
                "stratum": stratum,
                "exact_pairs": [["a", "b"]],
                "source_type_pairs": [["llm", "llm"], ["llm", "python"]],
                "cofailure_source_sets": [],
                "transition_directions": [["a", "b"]],
                "utilization_directions": [["a", "b"]],
                "text_repetition_pairs": [["a", "b"]],
            }
            for system_id in ("mathrouter", "icma", "mathgoal")
            for stratum in ("standard", "hard_gt_5")
        ],
    }
    config_path = tmp_path / "analysis-config.json"
    config_path.write_text(json.dumps(analysis_config), encoding="utf-8")
    analysis_path = tmp_path / "analysis.json"
    analysis = build_qualification_analysis(
        scoring_dir=scoring_output,
        config_path=config_path,
        output_path=analysis_path,
    )
    assert b"\r\n" not in analysis_path.read_bytes()
    assert analysis["episode_count"] == 150
    assert analysis["label_variant"] == "deterministic"
    assert len(analysis["panels"]) == 6
    assert analysis["system_ranking_computed"] is False
    assert {
        item["provenance_relation"] for item in analysis["panels"][0]["source_type_pairwise"]
    } == {"all", "same", "different"}
    analysis_schema = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "schemas/mathaudit-qualification-analysis-v0.1.schema.json"
        ).read_text(encoding="utf-8")
    )
    assert list(Draft202012Validator(analysis_schema).iter_errors(analysis)) == []

    adjudication_input = tmp_path / "adjudication-input"
    adjudication_input_manifest = prepare_qualification_adjudication(
        scoring_dir=scoring_output, output_dir=adjudication_input
    )
    adjudication_input_schema = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "schemas/mathaudit-qualification-adjudication-input-v0.1.schema.json"
        ).read_text(encoding="utf-8")
    )
    assert (
        list(
            Draft202012Validator(adjudication_input_schema).iter_errors(adjudication_input_manifest)
        )
        == []
    )
    combined = list(read_episodes(adjudication_input / "scored-episodes.jsonl"))
    bundle = tmp_path / "adjudication-bundle"
    export_adjudication_bundle(
        bundle,
        combined,
        blinding_key="fixture-blinding-key",
        guide_sha256="a" * 64,
        audit_sample_size=150,
        minimum_item_count=150,
    )
    rater_a = bundle / "public" / "rater_a.csv"
    rater_b = bundle / "public" / "rater_b.csv"
    _complete_agreeing_rater(rater_a, "fixture_a")
    _complete_agreeing_rater(rater_b, "fixture_b")
    agreement_dir = tmp_path / "agreement"
    agreement = agreement_and_conflicts(agreement_dir, rater_a, rater_b)
    assert agreement["disagreement_count"] == 0
    frozen = tmp_path / "frozen-adjudication"
    apply_adjudication(
        frozen,
        combined,
        bundle / "private" / "linkage.json",
        rater_a,
        rater_b,
        third_pass_path=agreement_dir / "third_pass.csv",
        guide_sha256="a" * 64,
    )
    adjudicated_scoring_dir = tmp_path / "adjudicated-scoring"
    adjudicated_scoring = freeze_qualification_adjudication(
        scoring_dir=scoring_output,
        adjudication_input_dir=adjudication_input,
        adjudication_dir=frozen,
        output_dir=adjudicated_scoring_dir,
        guide_version="1.0",
        guide_sha256="a" * 64,
    )
    adjudicated_scoring_schema = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "schemas/mathaudit-qualification-scoring-v0.2.schema.json"
        ).read_text(encoding="utf-8")
    )
    assert (
        list(Draft202012Validator(adjudicated_scoring_schema).iter_errors(adjudicated_scoring))
        == []
    )
    adjudicated_analysis_path = tmp_path / "analysis-adjudicated.json"
    adjudicated_analysis = build_qualification_analysis(
        scoring_dir=adjudicated_scoring_dir,
        config_path=config_path,
        output_path=adjudicated_analysis_path,
    )
    assert adjudicated_analysis["label_variant"] == "adjudicated"
    assert list(Draft202012Validator(analysis_schema).iter_errors(adjudicated_analysis)) == []

    with pytest.raises(ValueError, match="guide identity differs"):
        freeze_qualification_adjudication(
            scoring_dir=scoring_output,
            adjudication_input_dir=adjudication_input,
            adjudication_dir=frozen,
            output_dir=tmp_path / "rejected-guide-scoring",
            guide_version="1.0",
            guide_sha256="b" * 64,
        )

    mutated = tmp_path / "mutated-adjudication"
    shutil.copytree(frozen, mutated)
    mutated_path = mutated / "episodes.jsonl"
    mutated_episodes = list(read_episodes(mutated_path))
    mutated_episodes[0] = mutated_episodes[0].model_copy(
        update={
            "problem": mutated_episodes[0].problem.model_copy(
                update={"statement": "mutated after adjudication"}
            )
        }
    )
    write_episodes(mutated_path, mutated_episodes)
    mutated_manifest_path = mutated / "manifest.json"
    mutated_manifest = json.loads(mutated_manifest_path.read_text(encoding="utf-8"))
    mutated_manifest.pop("manifest_sha256")
    next(row for row in mutated_manifest["artifacts"] if row["path"] == "episodes.jsonl")[
        "sha256"
    ] = _file_sha256(mutated_path)
    mutated_manifest["manifest_sha256"] = sha256_json(mutated_manifest)
    mutated_manifest_path.write_text(json.dumps(mutated_manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="non-label episode content"):
        freeze_qualification_adjudication(
            scoring_dir=scoring_output,
            adjudication_input_dir=adjudication_input,
            adjudication_dir=mutated,
            output_dir=tmp_path / "rejected-mutated-scoring",
            guide_version="1.0",
            guide_sha256="a" * 64,
        )

    publication_dir = tmp_path / "qualification-publication"
    publication = write_qualification_publication_bundle(
        output_dir=publication_dir,
        analysis_paths=[analysis_path, adjudicated_analysis_path],
    )
    repeated = write_qualification_publication_bundle(
        output_dir=tmp_path / "qualification-publication-repeat",
        analysis_paths=[analysis_path, adjudicated_analysis_path],
    )
    assert publication == repeated
    assert publication["label_variants"] == ["adjudicated", "deterministic"]
    assert publication["system_ranking_computed"] is False
    assert len(list((publication_dir / "tables").glob("*.csv"))) == 10
    assert len(list((publication_dir / "figures").glob("*.svg"))) == 4
    assert len(list((publication_dir / "figures").glob("*.manifest.json"))) == 4
    publication_schema = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "schemas/mathaudit-qualification-publication-manifest-v0.1.schema.json"
        ).read_text(encoding="utf-8")
    )
    assert list(Draft202012Validator(publication_schema).iter_errors(publication)) == []
    publication_data = json.loads(
        (publication_dir / "publication-data.json").read_text(encoding="utf-8")
    )
    data_schema = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "schemas/mathaudit-qualification-publication-data-v0.1.schema.json"
        ).read_text(encoding="utf-8")
    )
    assert list(Draft202012Validator(data_schema).iter_errors(publication_data)) == []
    verified = verify_qualification_publication_bundle(
        bundle_dir=publication_dir,
        analysis_paths=[analysis_path, adjudicated_analysis_path],
    )
    assert verified["status"] == "passed"
    assert verified["artifact_count"] == 19
    reproduced = reproduce_and_compare_qualification_publication(
        analysis_paths=[analysis_path, adjudicated_analysis_path],
        reference_dir=publication_dir,
    )
    assert reproduced["byte_identical"] is True

    public_analysis = verify_public_analysis_release(analysis_path)
    assert public_analysis["contains_prompt_or_response_text"] is False
    assert public_analysis["reexecution_boundary"] == (
        "aggregate-analysis-to-publication-artifacts"
    )

    drift = publication_dir / "unregistered.txt"
    drift.write_text("drift", encoding="utf-8")
    with pytest.raises(ValueError, match="unregistered"):
        verify_qualification_publication_bundle(bundle_dir=publication_dir)
    drift.unlink()

    unsafe_analysis = copy.deepcopy(analysis)
    unsafe_analysis["gold"] = "private answer"
    unsafe_analysis.pop("analysis_sha256")
    unsafe_analysis["analysis_sha256"] = sha256_json(unsafe_analysis)
    unsafe_analysis_path = tmp_path / "unsafe-analysis.json"
    unsafe_analysis_path.write_text(json.dumps(unsafe_analysis), encoding="utf-8")
    with pytest.raises(ValueError, match="non-public key"):
        verify_public_analysis_release(unsafe_analysis_path)

    unsafe_analysis = copy.deepcopy(analysis)
    unsafe_analysis["provider_request_id"] = "req-private-linkage"
    unsafe_analysis["working_directory"] = "/home/researcher/private-run"
    unsafe_analysis.pop("analysis_sha256")
    unsafe_analysis["analysis_sha256"] = sha256_json(unsafe_analysis)
    unsafe_analysis_path.write_text(json.dumps(unsafe_analysis), encoding="utf-8")
    with pytest.raises(ValueError, match="non-public key.*local absolute path"):
        verify_public_analysis_release(unsafe_analysis_path)

    mutated_analysis_path = tmp_path / "mutated-analysis.json"
    mutated_analysis = copy.deepcopy(adjudicated_analysis)
    mutated_analysis["panels"][0]["episode_count"] = 24
    mutated_analysis_path.write_text(json.dumps(mutated_analysis), encoding="utf-8")
    with pytest.raises(ValueError, match="self-hash"):
        write_qualification_publication_bundle(
            output_dir=tmp_path / "rejected-publication",
            analysis_paths=[analysis_path, mutated_analysis_path],
        )


def _write_lineage_fixture(tmp_path, episode_factory):
    root_plan = _source_plan()
    first_state = _lineage_state(root_plan, 0, 10, failed_boundary=11)
    second_plan = _lineage_continuation_plan(root_plan, first_state, 11, "fixture-q6")
    second_state = _lineage_state(second_plan, 11, 26, failed_boundary=27)
    third_plan = _lineage_continuation_plan(second_plan, second_state, 27, "fixture-q7")
    third_state = _lineage_state(third_plan, 27, 149)
    plans = [root_plan, second_plan, third_plan]
    states = [first_state, second_state, third_state]
    plan_paths = []
    state_paths = []
    closeout_dirs = []
    ranges = [(0, 10), (11, 26), (27, 149)]
    for position, (plan, state, (start, end)) in enumerate(zip(plans, states, ranges, strict=True)):
        plan_path = tmp_path / ("plan-%d.json" % position)
        state_path = tmp_path / ("state-%d.json" % position)
        plan_path.write_text(json.dumps(plan), encoding="utf-8")
        state_path.write_text(json.dumps(state), encoding="utf-8")
        closeout = tmp_path / ("closeout-%d" % position)
        entries = [entry for entry in root_plan["entries"] if start <= entry["sequence"] <= end]
        _write_closeout(
            closeout,
            plan["authorization_id"],
            plan["plan_sha256"],
            _episodes(entries, episode_factory, "segment-%d" % position),
        )
        plan_paths.append(plan_path)
        state_paths.append(state_path)
        closeout_dirs.append(closeout)
    return plans, states, plan_paths, state_paths, closeout_dirs


def test_lineage_composite_assembles_three_segments_and_remains_scoreable(
    tmp_path, episode_factory
):
    plans, _states, plan_paths, state_paths, closeout_dirs = _write_lineage_fixture(
        tmp_path, episode_factory
    )
    output = tmp_path / "lineage-composite"
    manifest = assemble_qualification_lineage_composite(
        plan_paths=plan_paths,
        state_paths=state_paths,
        closeout_dirs=closeout_dirs,
        output_dir=output,
    )
    assert manifest["episode_count"] == 150
    assert [row["episode_count"] for row in manifest["lineage"]] == [11, 16, 123]
    assert [row["executor_terminal_status"] for row in manifest["lineage"]] == [
        "stopped_failure",
        "stopped_failure",
        "completed",
    ]
    index = json.loads((output / "sequence-index.json").read_text(encoding="utf-8"))
    assert [row["source_segment_position"] for row in index["records"]] == (
        [0] * 11 + [1] * 16 + [2] * 123
    )
    schema = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "schemas/mathaudit-qualification-composite-v0.2.schema.json"
        ).read_text(encoding="utf-8")
    )
    assert list(Draft202012Validator(schema).iter_errors(manifest)) == []
    scoring = score_qualification_composite(
        composite_dir=output, output_dir=tmp_path / "lineage-scoring"
    )
    assert scoring["source_plan_sha256"] == plans[0]["plan_sha256"]
    assert scoring["episode_count"] == 150


def test_lineage_composite_preserves_zero_complete_failed_segment(tmp_path, episode_factory):
    root_plan = _source_plan()
    q5_state = _lineage_state(root_plan, 0, 10, failed_boundary=11)
    q6_plan = _lineage_continuation_plan(root_plan, q5_state, 11, "fixture-q6")
    q6_state = _lineage_state(q6_plan, 11, 26, failed_boundary=27)
    q7_plan = _lineage_continuation_plan(q6_plan, q6_state, 27, "fixture-q7")
    q7_state = _lineage_state(q7_plan, 27, 26, failed_boundary=27)
    q8_plan = _lineage_continuation_plan(q7_plan, q7_state, 27, "fixture-q8")
    q8_state = _lineage_state(q8_plan, 27, 149)

    plans = [root_plan, q6_plan, q7_plan, q8_plan]
    states = [q5_state, q6_state, q7_state, q8_state]
    ranges = [(0, 10), (11, 26), (27, 26), (27, 149)]
    plan_paths = []
    state_paths = []
    closeout_dirs = []
    for position, (plan, state, (start, end)) in enumerate(zip(plans, states, ranges, strict=True)):
        plan_path = tmp_path / ("zero-plan-%d.json" % position)
        state_path = tmp_path / ("zero-state-%d.json" % position)
        plan_path.write_text(json.dumps(plan), encoding="utf-8")
        state_path.write_text(json.dumps(state), encoding="utf-8")
        closeout = tmp_path / ("zero-closeout-%d" % position)
        entries = [entry for entry in root_plan["entries"] if start <= entry["sequence"] <= end]
        _write_closeout(
            closeout,
            plan["authorization_id"],
            plan["plan_sha256"],
            _episodes(entries, episode_factory, "zero-segment-%d" % position),
        )
        plan_paths.append(plan_path)
        state_paths.append(state_path)
        closeout_dirs.append(closeout)

    output = tmp_path / "zero-lineage-composite"
    manifest = assemble_qualification_lineage_composite(
        plan_paths=plan_paths,
        state_paths=state_paths,
        closeout_dirs=closeout_dirs,
        output_dir=output,
    )
    assert [row["episode_count"] for row in manifest["lineage"]] == [11, 16, 0, 123]
    assert manifest["lineage"][2]["completed_sequence_start"] == 27
    assert manifest["lineage"][2]["completed_sequence_end"] is None
    schema = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "schemas/mathaudit-qualification-composite-v0.2.schema.json"
        ).read_text(encoding="utf-8")
    )
    assert list(Draft202012Validator(schema).iter_errors(manifest)) == []
    scoring = score_qualification_composite(
        composite_dir=output, output_dir=tmp_path / "zero-lineage-scoring"
    )
    assert scoring["episode_count"] == 150


def test_lineage_composite_rejects_provenance_tamper_and_missing_sequence(
    tmp_path, episode_factory
):
    _plans, _states, plan_paths, state_paths, closeout_dirs = _write_lineage_fixture(
        tmp_path, episode_factory
    )
    tampered_plan = json.loads(plan_paths[2].read_text(encoding="utf-8"))
    tampered_plan["continuation"]["source_state_sha256"] = "0" * 64
    tampered_plan.pop("plan_sha256")
    tampered_plan["plan_sha256"] = sha256_json(tampered_plan)
    tampered_plan_path = tmp_path / "tampered-plan.json"
    tampered_plan_path.write_text(json.dumps(tampered_plan), encoding="utf-8")
    with pytest.raises(ValueError, match="provenance mismatch"):
        assemble_qualification_lineage_composite(
            plan_paths=[plan_paths[0], plan_paths[1], tampered_plan_path],
            state_paths=state_paths,
            closeout_dirs=closeout_dirs,
            output_dir=tmp_path / "rejected-provenance",
        )

    missing_state = json.loads(state_paths[1].read_text(encoding="utf-8"))
    missing_state["episodes"].pop(5)
    missing_state.pop("state_sha256")
    missing_state["state_sha256"] = sha256_json(missing_state)
    missing_state_path = tmp_path / "missing-state.json"
    missing_state_path.write_text(json.dumps(missing_state), encoding="utf-8")
    relinked_plan = json.loads(plan_paths[2].read_text(encoding="utf-8"))
    relinked_plan["continuation"]["source_state_sha256"] = missing_state["state_sha256"]
    relinked_plan.pop("plan_sha256")
    relinked_plan["plan_sha256"] = sha256_json(relinked_plan)
    relinked_plan_path = tmp_path / "relinked-plan.json"
    relinked_plan_path.write_text(json.dumps(relinked_plan), encoding="utf-8")
    with pytest.raises(ValueError, match="sequence coverage"):
        assemble_qualification_lineage_composite(
            plan_paths=[plan_paths[0], plan_paths[1], relinked_plan_path],
            state_paths=[state_paths[0], missing_state_path, state_paths[2]],
            closeout_dirs=closeout_dirs,
            output_dir=tmp_path / "rejected-missing",
        )


def test_lineage_composite_rejects_replayed_boundary_and_completed_failure(
    tmp_path, episode_factory
):
    _plans, _states, plan_paths, state_paths, closeout_dirs = _write_lineage_fixture(
        tmp_path, episode_factory
    )
    duplicate_plan = json.loads(plan_paths[2].read_text(encoding="utf-8"))
    duplicate_plan["continuation"]["completed_prefix_episode_count"] = 11
    duplicate_plan["continuation"]["restart_sequence"] = 11
    duplicate_plan["entries"] = json.loads(plan_paths[1].read_text(encoding="utf-8"))["entries"]
    duplicate_plan.pop("plan_sha256")
    duplicate_plan["plan_sha256"] = sha256_json(duplicate_plan)
    duplicate_plan_path = tmp_path / "duplicate-plan.json"
    duplicate_plan_path.write_text(json.dumps(duplicate_plan), encoding="utf-8")
    with pytest.raises(ValueError, match="sequence coverage mismatch"):
        assemble_qualification_lineage_composite(
            plan_paths=[plan_paths[0], plan_paths[1], duplicate_plan_path],
            state_paths=state_paths,
            closeout_dirs=closeout_dirs,
            output_dir=tmp_path / "rejected-duplicate",
        )

    completed_boundary = json.loads(state_paths[1].read_text(encoding="utf-8"))
    completed_boundary["episodes"][-1]["status"] = "completed"
    completed_boundary["episodes"][-1]["attempts"][-1]["valid_full_trace"] = True
    completed_boundary.pop("state_sha256")
    completed_boundary["state_sha256"] = sha256_json(completed_boundary)
    completed_boundary_path = tmp_path / "completed-boundary-state.json"
    completed_boundary_path.write_text(json.dumps(completed_boundary), encoding="utf-8")
    relinked_plan = json.loads(plan_paths[2].read_text(encoding="utf-8"))
    relinked_plan["continuation"]["source_state_sha256"] = completed_boundary["state_sha256"]
    relinked_plan.pop("plan_sha256")
    relinked_plan["plan_sha256"] = sha256_json(relinked_plan)
    relinked_plan_path = tmp_path / "completed-boundary-plan.json"
    relinked_plan_path.write_text(json.dumps(relinked_plan), encoding="utf-8")
    with pytest.raises(ValueError, match="restart boundary was not failed"):
        assemble_qualification_lineage_composite(
            plan_paths=[plan_paths[0], plan_paths[1], relinked_plan_path],
            state_paths=[state_paths[0], completed_boundary_path, state_paths[2]],
            closeout_dirs=closeout_dirs,
            output_dir=tmp_path / "rejected-completed-boundary",
        )


def test_replacement_composite_overlays_one_missing_slot_and_validates_v03(
    tmp_path, episode_factory
):
    root_plan = _source_plan()
    base_state = _lineage_state(root_plan, 0, 148, failed_boundary=149)
    root_plan_path = tmp_path / "root-plan.json"
    base_state_path = tmp_path / "base-state.json"
    root_plan_path.write_text(json.dumps(root_plan), encoding="utf-8")
    base_state_path.write_text(json.dumps(base_state), encoding="utf-8")
    base_closeout = tmp_path / "base-closeout"
    _write_closeout(
        base_closeout,
        root_plan["authorization_id"],
        root_plan["plan_sha256"],
        _episodes(root_plan["entries"][:149], episode_factory, "base"),
    )

    inventory = {
        "format": "mathaudit-q13-postrun-replacement-inventory-v0.1",
        "outcome_blind": True,
        "contains_prompt_or_response_text": False,
        "complete_full_trace_slot_count": 149,
        "missing_full_trace_slot_count": 1,
        "missing_slots": [{"sequence": 149}],
        "lineage_states": [{"state_sha256": base_state["state_sha256"]}],
    }
    inventory["inventory_sha256"] = sha256_json(inventory)
    inventory_path = tmp_path / "inventory.json"
    inventory_path.write_text(json.dumps(inventory), encoding="utf-8")

    replacement_entry = copy.deepcopy(root_plan["entries"][149])
    replacement_plan = {
        "format": "mathaudit-qualification-execution-plan-v0.5",
        "authorization_id": "fixture-replacement",
        "replacement": {
            "source_schedule_plan_sha256": root_plan["plan_sha256"],
            "source_inventory_sha256": inventory["inventory_sha256"],
            "replacement_sequences": [149],
        },
        "entries": [replacement_entry],
    }
    replacement_plan["plan_sha256"] = sha256_json(replacement_plan)
    replacement_state = {
        "format": "mathaudit-qualification-executor-state-v0.4",
        "authorization_id": "fixture-replacement",
        "plan_sha256": replacement_plan["plan_sha256"],
        "status": "completed",
        "current_episodes": [],
        "episodes": [
            {
                "sequence": 149,
                "system_id": replacement_entry["system_id"],
                "idx": replacement_entry["idx"],
                "status": "completed",
                "attempts": [{"valid_full_trace": True}],
            }
        ],
    }
    replacement_state["state_sha256"] = sha256_json(replacement_state)
    replacement_plan_path = tmp_path / "replacement-plan.json"
    replacement_state_path = tmp_path / "replacement-state.json"
    replacement_plan_path.write_text(json.dumps(replacement_plan), encoding="utf-8")
    replacement_state_path.write_text(json.dumps(replacement_state), encoding="utf-8")
    replacement_closeout = tmp_path / "replacement-closeout"
    _write_closeout(
        replacement_closeout,
        replacement_plan["authorization_id"],
        replacement_plan["plan_sha256"],
        _episodes([replacement_entry], episode_factory, "replacement"),
    )

    output = tmp_path / "replacement-composite"
    manifest = assemble_qualification_replacement_composite(
        root_plan_path=root_plan_path,
        base_plan_paths=[root_plan_path],
        base_state_paths=[base_state_path],
        base_closeout_dirs=[base_closeout],
        replacement_plan_path=replacement_plan_path,
        replacement_state_path=replacement_state_path,
        replacement_closeout_dir=replacement_closeout,
        replacement_inventory_path=inventory_path,
        output_dir=output,
    )
    index = json.loads((output / "sequence-index.json").read_text(encoding="utf-8"))
    root = Path(__file__).resolve().parents[1]
    manifest_schema = json.loads(
        (root / "schemas/mathaudit-qualification-composite-v0.3.schema.json").read_text(
            encoding="utf-8"
        )
    )
    index_schema = json.loads(
        (root / "schemas/mathaudit-qualification-composite-index-v0.3.schema.json").read_text(
            encoding="utf-8"
        )
    )

    assert manifest["replacement"]["sequences"] == [149]
    assert manifest["episode_count"] == 150
    assert index["records"][149]["source_role"] == "replacement"
    assert list(Draft202012Validator(manifest_schema).iter_errors(manifest)) == []
    assert list(Draft202012Validator(index_schema).iter_errors(index)) == []

    scoring = score_qualification_composite(
        composite_dir=output, output_dir=tmp_path / "replacement-scoring"
    )
    assert scoring["episode_count"] == 150
