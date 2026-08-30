"""One-command, provider-free MathHarnessAudit fixture demonstration."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mathaudit.adapters import ICMAAdapter, RunContext
from mathaudit.ingest import load_problem_manifest
from mathaudit.io import write_episodes
from mathaudit.report import write_report
from mathaudit.scoring import score_episode
from mathaudit.validation import require_valid_episode


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=Path("tmp/fixture-demo"))
    args = parser.parse_args()

    fixture_root = Path(__file__).resolve().parent / "fixtures"
    contexts = load_problem_manifest(
        fixture_root / "problems.jsonl",
        dataset_id="fixture",
        split="test",
        stratum="easy",
    )
    payload = json.loads((fixture_root / "icma" / "0.json").read_text(encoding="utf-8"))
    run = RunContext(
        run_id="fixture-demo",
        system_id="icma-fixture",
        system_name="ICMA fixture",
        system_version="synthetic",
        harness_family="ICMA",
        seed=20260822,
    )
    episode = require_valid_episode(ICMAAdapter().convert(payload, contexts["0"], run))
    scored = require_valid_episode(score_episode(episode))

    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_episodes(args.output_dir / "canonical.jsonl", [episode])
    write_episodes(args.output_dir / "scored.jsonl", [scored])
    manifest = write_report(
        args.output_dir,
        [scored],
        pairs=[("reasoner", "python_executor")],
        bootstrap_replicates=100,
        seed=20260822,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
