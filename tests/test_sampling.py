import json

import pytest

from mathaudit.sampling import (
    public_sample_manifest,
    select_sample,
    verify_sample_manifest_hash,
)


def _records():
    return [
        {"id": "a1", "problem": "A", "answer": "secret-a", "level": 1, "domain": "Math -> A"},
        {"id": "a2", "problem": "B", "answer": "secret-b", "level": 1, "domain": "Math -> A"},
        {"id": "b1", "problem": "C", "answer": "secret-c", "level": 2, "domain": "Math -> B"},
        {"id": "b2", "problem": "D", "answer": "secret-d", "level": 2, "domain": "Math -> B"},
        {"id": "dup1", "problem": " duplicate ", "answer": "x", "level": 3, "domain": "Math -> C"},
        {"id": "dup2", "problem": "duplicate", "answer": "y", "level": 4, "domain": "Math -> C"},
    ]


def test_sample_is_order_invariant_balanced_and_excludes_duplicate_groups():
    first, diagnostics = select_sample(
        _records(),
        dataset_id="fixture",
        count=4,
        seed=17,
        id_field="id",
        difficulty_field="level",
        difficulty_gt=0,
        balance_field="domain",
        balance_depth=2,
        balance_mode="equal",
    )
    second, _ = select_sample(
        list(reversed(_records())),
        dataset_id="fixture",
        count=4,
        seed=17,
        id_field="id",
        difficulty_field="level",
        difficulty_gt=0,
        balance_field="domain",
        balance_depth=2,
        balance_mode="equal",
    )
    assert {item.source_id for item in first} == {item.source_id for item in second}
    assert diagnostics["duplicate_problem_groups_excluded"] == 1
    assert diagnostics["records_excluded_for_duplicate_problem"] == 2
    assert diagnostics["selected_by_balance_group"] == {"Math -> A": 2, "Math -> B": 2}


def test_public_manifest_contains_no_problem_answer_or_solution(tmp_path):
    source = tmp_path / "source.jsonl"
    source.write_text("{}\n", encoding="utf-8")
    selected, diagnostics = select_sample(
        _records(),
        dataset_id="fixture",
        count=2,
        seed=3,
        id_field="id",
        balance_field="domain",
        balance_depth=2,
    )
    manifest = public_sample_manifest(
        selected,
        source_path=source,
        dataset_id="fixture",
        dataset_version="v1",
        stratum="qualification",
        seed=3,
        selection_config={"count": 2},
        diagnostics=diagnostics,
    )
    rendered = json.dumps(manifest).lower()
    assert "secret-" not in rendered
    assert '"problem"' not in rendered
    assert '"answer"' not in rendered
    assert '"solution"' not in rendered
    assert manifest["privacy"]["contains_problem_text"] is False
    assert len(manifest["selected"]) == 2
    assert verify_sample_manifest_hash(manifest)
    manifest["dataset_version"] = "tampered"
    assert not verify_sample_manifest_hash(manifest)


def test_sample_rejects_duplicate_non_null_source_ids():
    records = _records()[:2]
    records[1]["id"] = records[0]["id"]
    with pytest.raises(ValueError, match="must be unique"):
        select_sample(
            records,
            dataset_id="fixture",
            count=1,
            seed=1,
            id_field="id",
        )


def test_proportional_sample_handles_nested_list_groups_and_missing_difficulty():
    records = [
        {
            "problem": "p%d" % index,
            "difficulty": None if index == 0 else index,
            "meta": {"domains": ["D%d -> leaf" % (index % 2)]},
        }
        for index in range(1, 8)
    ]
    records.append({"problem": "missing", "difficulty": None, "meta": {"domains": []}})
    selected, diagnostics = select_sample(
        records,
        dataset_id="nested",
        count=4,
        seed=2,
        difficulty_field="difficulty",
        difficulty_gt=1,
        difficulty_le=7,
        balance_field="meta.domains",
        balance_depth=1,
        balance_mode="proportional",
    )
    assert len(selected) == 4
    assert diagnostics["records_missing_required_difficulty"] == 1
    assert set(diagnostics["selected_by_balance_group"]) == {"D0", "D1"}


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"count": 0}, "count must be positive"),
        ({"count": 3}, "only 2 are eligible"),
        ({"count": 1, "balance_mode": "invalid"}, "balance mode"),
        ({"count": 1, "difficulty_field": "level"}, "is not numeric"),
    ],
)
def test_sample_rejects_invalid_requests(kwargs, message):
    records = [
        {"problem": "one", "level": "bad"},
        {"problem": "two", "level": "bad"},
    ]
    if "difficulty_field" not in kwargs:
        records = [{"problem": "one"}, {"problem": "two"}]
    with pytest.raises(ValueError, match=message):
        select_sample(records, dataset_id="fixture", seed=1, **kwargs)
