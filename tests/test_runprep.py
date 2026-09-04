# SPDX-License-Identifier: MIT

import json

import pytest

from mathaudit.ingest import load_problem_manifest
from mathaudit.runprep import prepare_matched_run_inputs, verify_input_bundle
from mathaudit.sampling import public_sample_manifest, select_sample


def _frozen_sample(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    source = tmp_path / "source.jsonl"
    records = [
        {"id": "a", "problem": "one", "answer": "1", "solution": "private one"},
        {"id": "b", "problem": "two", "answer": "2", "solution": "private two"},
    ]
    source.write_text("".join(json.dumps(row) + "\n" for row in records), encoding="utf-8")
    selected, diagnostics = select_sample(
        records, dataset_id="fixture", count=2, seed=3, id_field="id"
    )
    private_path = tmp_path / "private.jsonl"
    with private_path.open("w", encoding="utf-8") as handle:
        for item in selected:
            row = dict(item.record)
            row["_mathaudit"] = {
                "problem_sha256": item.problem_hash,
                "record_sha256": item.record_hash,
                "balance_group": item.balance_group,
            }
            handle.write(json.dumps(row) + "\n")
    manifest = public_sample_manifest(
        selected,
        source_path=source,
        dataset_id="fixture",
        dataset_version="v1",
        stratum="qualification",
        seed=3,
        selection_config={"statement_field": "problem"},
        diagnostics=diagnostics,
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return private_path, manifest_path


def test_prepare_run_inputs_separates_gold_and_preserves_public_problem_ids(tmp_path):
    private_path, manifest_path = _frozen_sample(tmp_path)
    output = tmp_path / "bundle"
    bundle = prepare_matched_run_inputs(
        private_samples=[private_path],
        public_manifests=[manifest_path],
        output_dir=output,
        system_ids=["mathgoal", "icma", "mathrouter"],
        schedule_seed=9,
    )
    competition = (output / "solver_visible" / "competition.jsonl").read_text(encoding="utf-8")
    mathgoal = (output / "solver_visible" / "mathgoal.jsonl").read_text(encoding="utf-8")
    audit = (output / "audit_only" / "problems.jsonl").read_text(encoding="utf-8")
    assert "answer" not in competition and "solution" not in competition
    assert "answer" not in mathgoal and "solution" not in mathgoal
    assert "private one" in audit and "private two" in audit
    assert bundle["task_count"] == 2
    assert all(sorted(task["system_order"]) == bundle["system_ids"] for task in bundle["tasks"])

    contexts = load_problem_manifest(
        output / "audit_only" / "problems.jsonl",
        dataset_id="qualification",
        split="test",
        stratum="qualification",
    )
    assert {value.problem_id for value in contexts.values()} == {
        task["problem_id"] for task in bundle["tasks"]
    }
    assert {value.dataset_id for value in contexts.values()} == {"fixture"}
    assert {value.dataset_version for value in contexts.values()} == {"v1"}
    assert {value.stratum for value in contexts.values()} == {"qualification"}
    assert verify_input_bundle(output)["bundle_sha256"] == bundle["bundle_sha256"]

    competition_path = output / "solver_visible" / "competition.jsonl"
    competition_path.write_text(competition + "{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="file hash mismatch"):
        verify_input_bundle(output)


def test_prepare_run_inputs_rejects_corruption_and_nonempty_destination(tmp_path):
    private_path, manifest_path = _frozen_sample(tmp_path)
    rows = [json.loads(line) for line in private_path.read_text(encoding="utf-8").splitlines()]
    rows[0]["answer"] = "tampered"
    private_path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    with pytest.raises(ValueError, match="record hash"):
        prepare_matched_run_inputs(
            private_samples=[private_path],
            public_manifests=[manifest_path],
            output_dir=tmp_path / "bundle",
            system_ids=["one"],
            schedule_seed=1,
        )

    private_path, manifest_path = _frozen_sample(tmp_path / "fresh")
    occupied = tmp_path / "occupied"
    occupied.mkdir()
    (occupied / "keep.txt").write_text("keep", encoding="utf-8")
    with pytest.raises(FileExistsError, match="absent or empty"):
        prepare_matched_run_inputs(
            private_samples=[private_path],
            public_manifests=[manifest_path],
            output_dir=occupied,
            system_ids=["one"],
            schedule_seed=1,
        )


def test_prepare_run_inputs_rejects_manifest_tampering(tmp_path):
    private_path, manifest_path = _frozen_sample(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["stratum"] = "changed"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="self-hash"):
        prepare_matched_run_inputs(
            private_samples=[private_path],
            public_manifests=[manifest_path],
            output_dir=tmp_path / "bundle",
            system_ids=["one"],
            schedule_seed=1,
        )
