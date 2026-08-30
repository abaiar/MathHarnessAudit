# SPDX-License-Identifier: MIT

import json

from mathaudit.report import build_audit_bundle, render_html, write_report


def test_report_bundle_and_html_are_self_contained(episode_factory, tmp_path):
    episodes = [
        episode_factory(0, True, True, True),
        episode_factory(1, False, True, True),
        episode_factory(2, False, False, False),
    ]
    bundle = build_audit_bundle(
        episodes,
        pairs=[("a", "b")],
        bootstrap_replicates=20,
        seed=9,
    )
    rendered = render_html(bundle)
    assert "MathHarnessAudit" in rendered
    assert "Repair and harm transitions" in rendered
    assert "<table>" in rendered

    manifest = write_report(
        tmp_path,
        episodes,
        pairs=[("a", "b")],
        bootstrap_replicates=20,
        seed=9,
    )
    assert manifest["episode_count"] == 3
    assert (tmp_path / "index.html").is_file()
    saved = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert saved["pairwise"][0]["complete_cases"] == 3
