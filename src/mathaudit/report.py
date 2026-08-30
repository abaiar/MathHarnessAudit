"""Machine-readable audit bundles and dependency-free static HTML reports."""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from . import __version__
from .hashing import sha256_json
from .metrics import (
    availability_profile,
    cofailure,
    conflict_adoption,
    cost_profile,
    final_outcome_profile,
    pairwise_dependence,
    provenance_support,
    transition_metrics,
)
from .models import Episode, SourceType


def _source_ids(episodes: Sequence[Episode]) -> List[str]:
    return sorted(
        {
            source.source_id
            for episode in episodes
            for source in episode.sources
            if source.source_type != SourceType.composite
        }
    )


def build_audit_bundle(
    episodes: Iterable[Episode],
    *,
    pairs: Optional[Sequence[Tuple[str, str]]] = None,
    bootstrap_replicates: int = 1000,
    seed: int = 20260822,
) -> Dict[str, Any]:
    episodes = list(episodes)
    source_ids = _source_ids(episodes)
    selected_pairs = list(pairs) if pairs is not None else list(combinations(source_ids, 2))
    availability = [availability_profile(episodes, source_id) for source_id in source_ids]
    costs = [cost_profile(episodes, source_id) for source_id in source_ids]
    pairwise = [
        pairwise_dependence(
            episodes,
            source_a,
            source_b,
            bootstrap_replicates=bootstrap_replicates,
            seed=seed,
        )
        for source_a, source_b in selected_pairs
    ]
    transitions = [transition_metrics(episodes, source_a, source_b) for source_a, source_b in selected_pairs]
    utilization = [conflict_adoption(episodes, source_a, source_b) for source_a, source_b in selected_pairs]
    provenance = [provenance_support(episode) for episode in episodes]
    return {
        "format": "mathaudit-report-v0.1",
        "tool_version": __version__,
        "episode_count": len(episodes),
        "system_ids": sorted({episode.system.system_id for episode in episodes}),
        "dataset_ids": sorted({episode.problem.dataset_id for episode in episodes}),
        "strata": sorted({episode.problem.stratum for episode in episodes}),
        "source_ids": source_ids,
        "availability": availability,
        "final_outcomes": final_outcome_profile(episodes),
        "cost": costs,
        "pairwise": pairwise,
        "cofailure": cofailure(episodes, source_ids) if source_ids else None,
        "transitions": transitions,
        "utilization": utilization,
        "provenance_support": provenance,
        "analysis_config": {
            "pairs": [list(pair) for pair in selected_pairs],
            "bootstrap_replicates": bootstrap_replicates,
            "seed": seed,
            "final_and_composite_sources_excluded_from_support": True,
        },
        "interpretation_limits": [
            "Dependence estimates are descriptive and use jointly binary-scorable evidence.",
            "Transition rates from selectively called sources are not causal effects.",
            "Different source labels do not imply independent provenance.",
            "Effective-support summaries are model-based and are not literal vote counts.",
        ],
    }


def _format_rate(value: Any) -> str:
    if value is None:
        return "—"
    return "%.3f" % float(value)


def _table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    head = "".join("<th>%s</th>" % html.escape(str(value)) for value in headers)
    body = "".join(
        "<tr>%s</tr>" % "".join("<td>%s</td>" % html.escape(str(value)) for value in row)
        for row in rows
    )
    return "<table><thead><tr>%s</tr></thead><tbody>%s</tbody></table>" % (head, body)


def render_html(bundle: Dict[str, Any]) -> str:
    availability_rows = [
        [
            item["source_id"],
            item["registered_episodes"],
            item["produced"],
            item["binary_scorable"],
            _format_rate(item["conditional_correctness"]),
            _format_rate(item["operational_support_rate"]),
        ]
        for item in bundle["availability"]
    ]
    pairwise_rows = [
        [
            item["source_a"],
            item["source_b"],
            item["complete_cases"],
            _format_rate(item["phi"]),
            _format_rate(item["joint_error_probability"]),
            item["cells"]["both_wrong"],
        ]
        for item in bundle["pairwise"]
    ]
    transition_rows = [
        [
            item["upstream"],
            item["checker"],
            _format_rate(item["repair_opportunity_rate"]),
            _format_rate(item["repair_realization_rate"]),
            _format_rate(item["harm_opportunity_rate"]),
            _format_rate(item["harm_realization_rate"]),
        ]
        for item in bundle["transitions"]
    ]
    utilization_rows = [
        [
            item["upstream"],
            item["checker"],
            item["counts"].get("binary_disagreements", 0),
            item["counts"].get("directly_observable", 0),
            _format_rate(item["direct_checker_adoption_rate"]),
            _format_rate(item["proxy_final_exact_match_rate"]),
        ]
        for item in bundle["utilization"]
    ]
    cost_rows = []
    for item in bundle.get("cost", []):
        metrics = item["metrics"]
        cost_rows.append(
            [
                item["source_id"],
                _format_rate(metrics["calls"]["median"]),
                _format_rate(metrics["total_tokens"]["median"]),
                _format_rate(metrics["latency_s"]["median"]),
                metrics["calls"]["n"],
                metrics["total_tokens"]["n"],
                metrics["latency_s"]["n"],
            ]
        )
    limitations = "".join("<li>%s</li>" % html.escape(value) for value in bundle["interpretation_limits"])
    cofailure_bundle = bundle.get("cofailure") or {}
    cofailure_text = _format_rate(cofailure_bundle.get("complete_case_beta"))
    operational_text = _format_rate(cofailure_bundle.get("operational_no_correct_support_rate"))
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>MathHarnessAudit report</title>
  <style>
    :root { color-scheme: light; --ink:#172033; --muted:#64748b; --line:#dbe3ee; --accent:#0f766e; --panel:#f8fafc; }
    body { max-width:1180px; margin:0 auto; padding:36px 24px 64px; font:15px/1.55 system-ui,sans-serif; color:var(--ink); background:white; }
    h1 { font-size:32px; margin:0 0 8px; } h2 { margin-top:34px; font-size:21px; }
    .lede { color:var(--muted); max-width:850px; }
    .cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:12px; margin:24px 0; }
    .card { background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:16px; }
    .card b { display:block; font-size:24px; color:var(--accent); } .card span { color:var(--muted); }
    table { width:100%%; border-collapse:collapse; margin:12px 0 24px; font-size:14px; }
    th,td { border-bottom:1px solid var(--line); padding:9px 10px; text-align:left; vertical-align:top; }
    th { background:var(--panel); font-weight:650; }
    code { background:#eef2f7; padding:2px 5px; border-radius:4px; }
    .warning { border-left:4px solid #d97706; background:#fff7ed; padding:12px 16px; }
  </style>
</head>
<body>
  <h1>MathHarnessAudit</h1>
  <p class="lede">Outcome-linked evidence audit. Missing and abstaining evidence are preserved separately from incorrect evidence; all dependence estimates use explicitly stated complete-case populations.</p>
  <div class="cards">
    <div class="card"><b>%s</b><span>episodes</span></div>
    <div class="card"><b>%s</b><span>systems</span></div>
    <div class="card"><b>%s</b><span>upstream sources</span></div>
    <div class="card"><b>%s</b><span>complete-case co-failure β</span></div>
    <div class="card"><b>%s</b><span>operational no-correct-support</span></div>
  </div>
  <h2>Availability and correctness</h2>
  %s
  <h2>Pairwise error dependence</h2>
  %s
  <h2>Repair and harm transitions</h2>
  %s
  <h2>Conflict adoption</h2>
  %s
  <h2>Measured cost coverage</h2>
  %s
  <h2>Interpretation limits</h2>
  <div class="warning"><ul>%s</ul></div>
  <p class="lede">Generated by MathHarnessAudit %s. The accompanying <code>report.json</code> and <code>manifest.json</code> are authoritative machine-readable artifacts.</p>
</body>
</html>
""" % (
        bundle["episode_count"],
        len(bundle["system_ids"]),
        len(bundle["source_ids"]),
        cofailure_text,
        operational_text,
        _table(["Source", "Episodes", "Produced", "Binary scorable", "Conditional correctness", "Operational support"], availability_rows),
        _table(["Source A", "Source B", "Complete cases", "Phi", "Joint error", "Both wrong"], pairwise_rows),
        _table(["Upstream", "Checker", "Repair opportunity", "Repair realization", "Harm opportunity", "Harm realization"], transition_rows),
        _table(["Upstream", "Checker", "Disagreements", "Directly observable", "Direct checker adoption", "Final exact-match proxy"], utilization_rows),
        _table(["Source", "Median calls", "Median tokens", "Median latency s", "n calls", "n tokens", "n latency"], cost_rows),
        limitations,
        html.escape(str(bundle["tool_version"])),
    )


def write_report(
    output_dir: Path,
    episodes: Iterable[Episode],
    *,
    pairs: Optional[Sequence[Tuple[str, str]]] = None,
    bootstrap_replicates: int = 1000,
    seed: int = 20260822,
) -> Dict[str, Any]:
    episodes = list(episodes)
    bundle = build_audit_bundle(
        episodes,
        pairs=pairs,
        bootstrap_replicates=bootstrap_replicates,
        seed=seed,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    report_text = json.dumps(bundle, ensure_ascii=False, indent=2) + "\n"
    html_text = render_html(bundle)
    report_path = output_dir / "report.json"
    html_path = output_dir / "index.html"
    report_path.write_text(report_text, encoding="utf-8")
    html_path.write_text(html_text, encoding="utf-8")
    episode_payload = [episode.model_dump(mode="json", exclude_none=False) for episode in episodes]
    manifest = {
        "format": "mathaudit-manifest-v0.1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "tool_version": __version__,
        "episode_count": len(episodes),
        "episode_bundle_sha256": sha256_json(episode_payload),
        "analysis_config_sha256": sha256_json(bundle["analysis_config"]),
        "report_json_sha256": sha256_json(bundle),
        "files": ["report.json", "index.html", "manifest.json"],
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest
