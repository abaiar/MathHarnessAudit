# SPDX-License-Identifier: MIT

import csv
import json

import pytest

from mathaudit.adjudication import (
    RATER_FIELDS,
    THIRD_FIELDS,
    agreement_and_conflicts,
    apply_adjudication,
    export_adjudication_bundle,
)
from mathaudit.io import read_episodes
from mathaudit.models import AdjudicationStatus, LabelValue, ScorerType

GUIDE_SHA256 = "a" * 64


def _complete_rater(path, *, annotator, labels):
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for index, row in enumerate(rows):
        row.update(
            {
                "annotator_id": annotator,
                "label": labels[row["adjudication_id"]],
                "confidence": "high" if index % 2 == 0 else "medium",
                "reason_code": "exact",
                "rationale": "Independent mathematical comparison.",
                "timestamp_utc": "2026-08-23T01:%02d:00Z" % index,
            }
        )
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RATER_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _complete_third(path, annotator="reviewer_c"):
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for index, row in enumerate(rows):
        row.update(
            {
                "third_annotator_id": annotator,
                "final_label": "incorrect",
                "confidence": "high",
                "reason_code": "missing_component",
                "rationale": "The requested second component is absent.",
                "timestamp_utc": "2026-08-23T02:%02d:00Z" % index,
                "final_resolution": "resolved",
            }
        )
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=THIRD_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def test_export_is_blinded_stratified_and_deterministic(episode_factory, tmp_path):
    episodes = [
        episode_factory(0, True, False, True),
        episode_factory(1, False, True, False),
    ]
    episodes[0].labels[0].value = LabelValue.unscorable
    first = export_adjudication_bundle(
        tmp_path / "first",
        episodes,
        blinding_key="qualification-secret",
        guide_sha256=GUIDE_SHA256,
        audit_sample_size=2,
    )
    second = export_adjudication_bundle(
        tmp_path / "second",
        episodes,
        blinding_key="qualification-secret",
        guide_sha256=GUIDE_SHA256,
        audit_sample_size=2,
    )
    assert first == second
    assert first["item_count"] == 3
    rater_text = (tmp_path / "first" / "public" / "rater_a.csv").read_text(
        encoding="utf-8-sig"
    )
    assert "synthetic" not in rater_text
    assert "unscorable" not in rater_text
    linkage = json.loads((tmp_path / "first" / "private" / "linkage.json").read_text())
    assert linkage["blinding_key_sha256"] != "qualification-secret"
    assert linkage["guide_sha256"] == GUIDE_SHA256
    assert {item["proposed_label"] for item in linkage["items"]} >= {
        "unscorable",
        "correct",
    }

    with pytest.raises(ValueError, match="minimum_item_count"):
        export_adjudication_bundle(
            tmp_path / "too-small",
            episodes,
            blinding_key="qualification-secret",
            guide_sha256=GUIDE_SHA256,
            audit_sample_size=2,
            minimum_item_count=4,
        )


def test_agreement_then_third_pass_and_frozen_apply(episode_factory, tmp_path):
    episodes = [episode_factory(0, True, False, True)]
    episodes[0].labels[0].value = LabelValue.unscorable
    bundle = tmp_path / "bundle"
    export_adjudication_bundle(
        bundle,
        episodes,
        blinding_key="qualification-secret",
        guide_sha256=GUIDE_SHA256,
        audit_sample_size=1,
    )
    rater_a = bundle / "public" / "rater_a.csv"
    rater_b = bundle / "public" / "rater_b.csv"
    with rater_a.open("r", encoding="utf-8-sig", newline="") as handle:
        item_ids = [row["adjudication_id"] for row in csv.DictReader(handle)]
    labels_a = {item_id: "correct" for item_id in item_ids}
    labels_b = dict(labels_a)
    labels_b[item_ids[0]] = "incorrect"
    _complete_rater(rater_a, annotator="reviewer_a", labels=labels_a)
    _complete_rater(rater_b, annotator="reviewer_b", labels=labels_b)

    agreement_dir = tmp_path / "agreement"
    report = agreement_and_conflicts(agreement_dir, rater_a, rater_b)
    assert report["item_count"] == 2
    assert report["disagreement_count"] == 1
    assert report["raw_agreement"] == 0.5
    _complete_third(agreement_dir / "third_pass.csv", annotator="reviewer_a")

    with pytest.raises(ValueError, match="must differ from both"):
        apply_adjudication(
            tmp_path / "rejected-same-third",
            episodes,
            bundle / "private" / "linkage.json",
            rater_a,
            rater_b,
            third_pass_path=agreement_dir / "third_pass.csv",
            guide_sha256=GUIDE_SHA256,
        )
    _complete_third(agreement_dir / "third_pass.csv")

    with pytest.raises(ValueError, match="guide identity differs"):
        apply_adjudication(
            tmp_path / "rejected-guide-drift",
            episodes,
            bundle / "private" / "linkage.json",
            rater_a,
            rater_b,
            third_pass_path=agreement_dir / "third_pass.csv",
            guide_sha256="b" * 64,
        )

    original_label_count = len(episodes[0].labels)
    result_dir = tmp_path / "frozen"
    manifest = apply_adjudication(
        result_dir,
        episodes,
        bundle / "private" / "linkage.json",
        rater_a,
        rater_b,
        third_pass_path=agreement_dir / "third_pass.csv",
        guide_sha256=GUIDE_SHA256,
    )
    assert manifest["item_count"] == 2
    frozen = list(read_episodes(result_dir / "episodes.jsonl"))[0]
    assert len(frozen.labels) == original_label_count + 6
    finals = [label for label in frozen.labels if label.scorer_type == ScorerType.adjudicated]
    assert len(finals) == 2
    assert all(label.adjudication_status == AdjudicationStatus.resolved for label in finals)
    assert any(label.value == LabelValue.incorrect for label in finals)
    assert all(label.metadata["rationale_sha256"] for label in finals)


def test_agreement_rejects_same_annotator(episode_factory, tmp_path):
    bundle = tmp_path / "bundle"
    export_adjudication_bundle(
        bundle,
        [episode_factory(0, True, False, True)],
        blinding_key="qualification-secret",
        guide_sha256=GUIDE_SHA256,
        audit_sample_size=1,
    )
    rater_a = bundle / "public" / "rater_a.csv"
    rater_b = bundle / "public" / "rater_b.csv"
    with rater_a.open("r", encoding="utf-8-sig", newline="") as handle:
        ids = [row["adjudication_id"] for row in csv.DictReader(handle)]
    labels = {item_id: "correct" for item_id in ids}
    _complete_rater(rater_a, annotator="same", labels=labels)
    _complete_rater(rater_b, annotator="same", labels=labels)
    with pytest.raises(ValueError, match="must differ"):
        agreement_and_conflicts(tmp_path / "agreement", rater_a, rater_b)


def test_apply_rejects_missing_third_pass(episode_factory, tmp_path):
    episodes = [episode_factory(0, True, False, True)]
    bundle = tmp_path / "bundle"
    export_adjudication_bundle(
        bundle,
        episodes,
        blinding_key="qualification-secret",
        guide_sha256=GUIDE_SHA256,
        audit_sample_size=1,
    )
    rater_a = bundle / "public" / "rater_a.csv"
    rater_b = bundle / "public" / "rater_b.csv"
    with rater_a.open("r", encoding="utf-8-sig", newline="") as handle:
        ids = [row["adjudication_id"] for row in csv.DictReader(handle)]
    _complete_rater(rater_a, annotator="a", labels={item_id: "correct" for item_id in ids})
    _complete_rater(rater_b, annotator="b", labels={item_id: "incorrect" for item_id in ids})
    with pytest.raises(ValueError, match="exactly equal"):
        apply_adjudication(
            tmp_path / "frozen",
            episodes,
            bundle / "private" / "linkage.json",
            rater_a,
            rater_b,
            guide_sha256=GUIDE_SHA256,
        )


def test_apply_rejects_identically_tampered_rater_display(episode_factory, tmp_path):
    episodes = [episode_factory(0, True, False, True)]
    bundle = tmp_path / "bundle"
    export_adjudication_bundle(
        bundle,
        episodes,
        blinding_key="qualification-secret",
        guide_sha256=GUIDE_SHA256,
        audit_sample_size=1,
    )
    rater_a = bundle / "public" / "rater_a.csv"
    rater_b = bundle / "public" / "rater_b.csv"
    with rater_a.open("r", encoding="utf-8-sig", newline="") as handle:
        ids = [row["adjudication_id"] for row in csv.DictReader(handle)]
    labels = {item_id: "correct" for item_id in ids}
    _complete_rater(rater_a, annotator="a", labels=labels)
    _complete_rater(rater_b, annotator="b", labels=labels)
    for path in (rater_a, rater_b):
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        for row in rows:
            row["reference_answer"] = "identically tampered reference"
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=RATER_FIELDS)
            writer.writeheader()
            writer.writerows(rows)
    agreement_dir = tmp_path / "agreement"
    agreement_and_conflicts(agreement_dir, rater_a, rater_b)
    with pytest.raises(ValueError, match="rater display material changed"):
        apply_adjudication(
            tmp_path / "frozen",
            episodes,
            bundle / "private" / "linkage.json",
            rater_a,
            rater_b,
            third_pass_path=agreement_dir / "third_pass.csv",
            guide_sha256=GUIDE_SHA256,
        )
