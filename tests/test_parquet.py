# SPDX-License-Identifier: MIT

import pandas as pd
import pytest

from mathaudit.parquet import write_parquet_bundle

pyarrow = pytest.importorskip("pyarrow")


def test_parquet_bundle_round_trip(episode_factory, tmp_path):
    paths = write_parquet_bundle(
        tmp_path,
        [episode_factory(0, True, False, True)],
    )
    assert len(paths) == 7
    episodes = pd.read_parquet(tmp_path / "episodes.parquet")
    evidence = pd.read_parquet(tmp_path / "evidence.parquet")
    decisions = pd.read_parquet(tmp_path / "decisions.parquet")
    assert episodes.loc[0, "episode_id"] == "episode:0"
    assert len(evidence) == 3
    assert decisions.empty
