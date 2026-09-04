# SPDX-License-Identifier: MIT

import csv

import pytest

from mathaudit.publication import build_publication_data, write_publication_bundle


def _config():
    return {
        "format": "mathaudit-publication-config-v0.1",
        "minimum_complete_cases": 2,
        "bootstrap_replicates": 20,
        "seed": 9,
        "panels": [
            {
                "panel_id": "synthetic-oracle",
                "system_id": "synthetic",
                "stratum": "oracle",
                "source_ids": ["a", "b"],
                "cofailure_source_ids": ["a", "b"],
                "pair": ["a", "b"],
                "transition_direction": ["a", "b"],
                "utilization_direction": ["a", "b"],
            }
        ],
    }


def test_publication_bundle_is_deterministic_and_hashes_every_artifact(episode_factory, tmp_path):
    episodes = [
        episode_factory(0, True, True, True),
        episode_factory(1, False, True, True),
        episode_factory(2, False, False, False),
    ]
    first = write_publication_bundle(tmp_path / "first", episodes, _config())
    second = write_publication_bundle(tmp_path / "second", episodes, _config())
    assert first == second
    assert len(first["artifacts"]) == 14
    assert all(len(item["sha256"]) == 64 for item in first["artifacts"])

    pair_rows = list(
        csv.DictReader((tmp_path / "first" / "tables" / "pairwise.csv").open(encoding="utf-8"))
    )
    assert pair_rows[0]["complete_cases"] == "3"
    assert pair_rows[0]["precision_flag"] == "adequate"
    svg = (tmp_path / "first" / "figures" / "dependence_cofailure.svg").read_text(encoding="utf-8")
    assert "<title" in svg and "all-wrong beta" in svg
    assert "nan" not in svg.lower()


def test_publication_data_uses_exact_panels_and_marks_small_cells(episode_factory):
    config = _config()
    config["minimum_complete_cases"] = 10
    data = build_publication_data(
        [episode_factory(0, True, False, True), episode_factory(1, False, False, False)],
        config,
    )
    panel = data["panels"][0]
    assert panel["episode_count"] == 2
    assert panel["pairwise"]["precision_flag"] == "imprecise"
    assert panel["cofailure"]["complete_cases"] == 2
    assert panel["availability"][0]["intervals_exact_95"]["conditional_correctness"][0] is not None


@pytest.mark.parametrize(
    "mutation",
    [
        lambda config: config.update(format="wrong"),
        lambda config: config.update(panels=[]),
        lambda config: config["panels"][0].update(pair=["a", "missing"]),
        lambda config: config["panels"][0].update(source_ids=["a", "a"]),
        lambda config: config["panels"][0].update(cofailure_source_ids=["a", "missing"]),
    ],
)
def test_publication_config_rejects_invalid_panels(episode_factory, mutation):
    config = _config()
    mutation(config)
    with pytest.raises(ValueError):
        build_publication_data([episode_factory(0, True, True, True)], config)


def test_publication_refuses_missing_or_nonempty_panel(episode_factory, tmp_path):
    config = _config()
    config["panels"][0]["stratum"] = "absent"
    with pytest.raises(ValueError, match="no matching episodes"):
        build_publication_data([episode_factory(0, True, True, True)], config)

    occupied = tmp_path / "occupied"
    occupied.mkdir()
    (occupied / "keep.txt").write_text("keep", encoding="utf-8")
    with pytest.raises(FileExistsError, match="absent or empty"):
        write_publication_bundle(occupied, [episode_factory(0, True, True, True)], _config())


def test_publication_rejects_registered_source_absent_from_panel(episode_factory):
    config = _config()
    config["panels"][0]["source_ids"].append("never_observed")
    with pytest.raises(ValueError, match="unobserved registered source"):
        build_publication_data([episode_factory(0, True, True, True)], config)
