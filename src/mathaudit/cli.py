# SPDX-License-Identifier: MIT

"""Command-line interface for MathHarnessAudit."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from .adapters import RunContext
from .adjudication import (
    agreement_and_conflicts,
    apply_adjudication,
    export_adjudication_bundle,
)
from .budget import initialize_budget_ledger
from .coverage import adapter_coverage
from .execution import (
    compile_qualification_continuation_plan,
    compile_qualification_execution_plan,
    compile_qualification_replacement_plan,
    verify_qualification_execution_plan,
)
from .executor_state import migrate_executor_state_v03
from .fingerprint import (
    fingerprint_source_tree,
    verify_source_fingerprint,
    write_source_fingerprint,
)
from .ingest import ingest_payloads, iter_payloads, load_problem_manifest
from .io import read_episodes, write_episodes
from .metrics import (
    availability_profile,
    cofailure,
    pairwise_dependence,
    transition_metrics,
)
from .migration import migrate_episode_v1
from .qualification import (
    prepare_qualification_run_manifests,
    run_qualification_preflight,
    verify_qualification_authorization,
)
from .qualification_analysis import build_qualification_analysis
from .qualification_closeout import closeout_qualification
from .qualification_composite import (
    assemble_qualification_composite,
    assemble_qualification_lineage_composite,
    assemble_qualification_replacement_composite,
)
from .qualification_forecast import DEFAULT_SCENARIOS, write_qualification_forecast
from .qualification_publication import (
    reproduce_and_compare_qualification_publication,
    verify_public_analysis_release,
    verify_qualification_publication_bundle,
    write_qualification_publication_bundle,
)
from .qualification_scoring import (
    freeze_qualification_adjudication,
    prepare_qualification_adjudication,
    score_qualification_composite,
)
from .report import write_report
from .runprep import prepare_matched_run_inputs, verify_input_bundle
from .sampling import public_sample_manifest, select_sample, verify_sample_manifest_hash
from .schema_resources import export_schemas, schema_names
from .scoring import score_episode
from .validation import validate_episode

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Outcome-linked evidence auditing for mathematical reasoning agents.",
)
console = Console()


@app.command("list-schemas")
def list_schemas_command() -> None:
    """List JSON Schemas embedded in the installed package."""

    for name in schema_names():
        console.print(name)


@app.command("export-schemas")
def export_schemas_command(
    output_dir: Path = typer.Option(..., "--output-dir"),
) -> None:
    """Export the installed JSON Schemas to a new or empty directory."""

    written = export_schemas(output_dir)
    console.print(f"Exported {len(written)} JSON Schemas to {output_dir}.")


@app.command("ingest")
def ingest_command(
    adapter: str = typer.Option(
        ...,
        help="Built-in adapter: canonical, icma, mathgoal, mathrouter, or otel.",
    ),
    input_path: Path = typer.Option(..., "--input", exists=True, readable=True),
    input_glob: Optional[str] = typer.Option(
        None, "--input-glob", help="Glob used when --input is a directory."
    ),
    problems_path: Path = typer.Option(..., "--problems", exists=True, readable=True),
    output_path: Path = typer.Option(..., "--output"),
    dataset_id: str = typer.Option(...),
    split: str = typer.Option("test"),
    stratum: str = typer.Option(...),
    run_id: str = typer.Option(...),
    system_id: str = typer.Option(...),
    system_name: str = typer.Option(...),
    system_version: str = typer.Option(...),
    harness_family: Optional[str] = typer.Option(None),
    repository: Optional[str] = typer.Option(None),
    commit: Optional[str] = typer.Option(None),
    seed: Optional[int] = typer.Option(None),
    limit: Optional[int] = typer.Option(None, min=1),
) -> None:
    """Convert legacy traces to canonical JSONL and validate every episode."""

    problems = load_problem_manifest(
        problems_path,
        dataset_id=dataset_id,
        split=split,
        stratum=stratum,
    )
    run = RunContext(
        run_id=run_id,
        system_id=system_id,
        system_name=system_name,
        system_version=system_version,
        harness_family=harness_family,
        repository=repository,
        commit=commit,
        seed=seed,
    )
    try:
        episodes = ingest_payloads(
            iter_payloads(input_path, input_glob),
            adapter_name=adapter,
            problems=problems,
            run=run,
            limit=limit,
        )
    except (ValueError, KeyError) as exc:
        # Keep diagnostics as one plain line so callers and CI can reliably
        # match the actionable failure text even when Rich's terminal width
        # wrapping would otherwise split the message.
        typer.echo(f"Ingestion failed: {exc}")
        raise typer.Exit(code=2) from exc
    write_episodes(output_path, episodes)
    console.print(json.dumps(adapter_coverage(episodes), ensure_ascii=False, indent=2))


@app.command("validate")
def validate_command(input_path: Path = typer.Argument(..., exists=True, readable=True)) -> None:
    """Validate canonical episode structure and cross-reference semantics."""

    episode_count = 0
    issue_count = 0
    for episode in read_episodes(input_path):
        episode_count += 1
        issues = validate_episode(episode)
        issue_count += len(issues)
        for issue in issues:
            console.print(
                "[%s] %s %s: %s" % (issue.severity.upper(), issue.code, issue.path, issue.message)
            )
    if issue_count:
        raise typer.Exit(code=1)
    console.print("Validated %d episode(s); no semantic issues." % episode_count)


@app.command("migrate-episode-v1")
def migrate_episode_v1_command(
    input_path: Path = typer.Argument(..., exists=True, readable=True),
    output_path: Path = typer.Option(..., "--output"),
) -> None:
    """Losslessly migrate canonical episode JSONL from v0.1 to v1.0."""

    if output_path.exists():
        console.print("[ERROR] output already exists: %s" % output_path)
        raise typer.Exit(code=1)
    episodes = [migrate_episode_v1(episode) for episode in read_episodes(input_path)]
    write_episodes(output_path, episodes)
    console.print("Migrated %d canonical episode(s) to schema v1.0." % len(episodes))


@app.command("coverage")
def coverage_command(
    input_path: Path = typer.Argument(..., exists=True, readable=True),
    output_path: Optional[Path] = typer.Option(None, "--output"),
) -> None:
    """Summarize adapter fidelity and observable evidence structure."""

    report = adapter_coverage(read_episodes(input_path))
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if output_path is None:
        console.print(rendered)
    else:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered + "\n", encoding="utf-8")
        console.print("Wrote %s" % output_path)


@app.command("fingerprint-source")
def fingerprint_source_command(
    root: Path = typer.Argument(..., exists=True, file_okay=False, readable=True),
    system_id: str = typer.Option(..., "--system-id"),
    output_path: Path = typer.Option(..., "--output"),
    exclude_path: Optional[list[str]] = typer.Option(
        None,
        "--exclude-path",
        help="Repeat for a root-relative file or directory excluded by frozen policy.",
    ),
) -> None:
    """Create a locale-independent, self-hashed source-tree inventory."""

    manifest = fingerprint_source_tree(
        root,
        system_id=system_id,
        excluded_paths=exclude_path or [],
    )
    write_source_fingerprint(output_path, manifest)
    console.print(
        json.dumps(
            {
                "system_id": manifest["system_id"],
                "file_count": manifest["file_count"],
                "manifest_sha256": manifest["manifest_sha256"],
                "self_sha256": manifest["self_sha256"],
                "output": str(output_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


@app.command("verify-source-fingerprint")
def verify_source_fingerprint_command(
    root: Path = typer.Argument(..., exists=True, file_okay=False, readable=True),
    manifest_path: Path = typer.Option(..., "--manifest", exists=True, readable=True),
) -> None:
    """Verify a source tree against an explicit cross-platform file inventory."""

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    console.print(json.dumps(verify_source_fingerprint(root, manifest), indent=2))


@app.command("verify-qualification-authorization")
def verify_qualification_authorization_command(
    input_path: Path = typer.Argument(..., exists=True, readable=True),
    schema_path: Optional[Path] = typer.Option(None, "--schema", exists=True, readable=True),
) -> None:
    """Require a structurally and semantically runnable Q authorization record."""

    payload = json.loads(input_path.read_text(encoding="utf-8"))
    if schema_path is not None:
        try:
            from jsonschema import Draft202012Validator
        except ImportError as exc:
            raise RuntimeError(
                "JSON Schema validation requires the 'schema' extra: "
                "pip install 'math-harness-audit[schema]'"
            ) from exc
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        errors = sorted(
            Draft202012Validator(schema).iter_errors(payload),
            key=lambda item: list(item.path),
        )
        if errors:
            raise typer.BadParameter(
                "authorization Schema errors: " + "; ".join(error.message for error in errors)
            )
    console.print(json.dumps(verify_qualification_authorization(payload), indent=2))


@app.command("qualification-preflight")
def qualification_preflight_command(
    config_path: Path = typer.Option(..., "--config", exists=True, readable=True),
    output_path: Optional[Path] = typer.Option(None, "--output"),
) -> None:
    """Run all provider-free gates and fail closed before Q model contact."""

    report = run_qualification_preflight(config_path)
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if output_path is not None:
        if output_path.exists():
            raise FileExistsError("preflight output already exists: %s" % output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered, encoding="utf-8")
    console.print(rendered.rstrip())
    if not report["ready"]:
        raise typer.Exit(code=1)


@app.command("qualification-closeout")
def qualification_closeout_command(
    authorization_path: Path = typer.Option(..., "--authorization", exists=True),
    ledger_path: Path = typer.Option(..., "--ledger", exists=True),
    plan_path: Path = typer.Option(..., "--plan", exists=True),
    bundle_manifest_path: Path = typer.Option(..., "--bundle-manifest", exists=True),
    executor_state_path: Path = typer.Option(..., "--executor-state", exists=True),
    raw_dir: Path = typer.Option(..., "--raw-dir", exists=True, file_okay=False),
    problems_path: Path = typer.Option(..., "--problems", exists=True),
    planned_manifest_dir: Path = typer.Option(
        ..., "--planned-manifest-dir", exists=True, file_okay=False
    ),
    output_dir: Path = typer.Option(..., "--output-dir"),
    source_plan_path: Optional[Path] = typer.Option(
        None, "--source-plan", exists=True, dir_okay=False
    ),
    source_state_path: Optional[Path] = typer.Option(
        None, "--source-state", exists=True, dir_okay=False
    ),
    replacement_inventory_path: Optional[Path] = typer.Option(
        None, "--replacement-inventory", exists=True, dir_okay=False
    ),
) -> None:
    """Close a Q run with health/coverage artifacts but no outcome aggregates."""

    result = closeout_qualification(
        authorization_path=authorization_path,
        ledger_path=ledger_path,
        plan_path=plan_path,
        bundle_manifest_path=bundle_manifest_path,
        executor_state_path=executor_state_path,
        raw_dir=raw_dir,
        problems_path=problems_path,
        planned_manifest_dir=planned_manifest_dir,
        output_dir=output_dir,
        source_plan_path=source_plan_path,
        source_state_path=source_state_path,
        replacement_inventory_path=replacement_inventory_path,
    )
    console.print(json.dumps(result, ensure_ascii=False, indent=2))


@app.command("migrate-qualification-state")
def migrate_qualification_state_command(
    source_path: Path = typer.Option(..., "--source", exists=True, dir_okay=False),
    output_path: Path = typer.Option(..., "--output", dir_okay=False),
) -> None:
    """Migrate a terminal v0.1/v0.2 executor state to provenance-linked v0.3."""

    if output_path.exists():
        raise FileExistsError("migrated state output already exists: %s" % output_path)
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    migrated = migrate_executor_state_v03(payload)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(migrated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    console.print(json.dumps(migrated, ensure_ascii=False, indent=2))


@app.command("qualification-composite")
def qualification_composite_command(
    source_plan_path: Path = typer.Option(..., "--source-plan", exists=True),
    prefix_state_path: Path = typer.Option(..., "--prefix-state", exists=True),
    continuation_plan_path: Path = typer.Option(..., "--continuation-plan", exists=True),
    continuation_state_path: Path = typer.Option(..., "--continuation-state", exists=True),
    prefix_closeout_dir: Path = typer.Option(
        ..., "--prefix-closeout", exists=True, file_okay=False
    ),
    continuation_closeout_dir: Path = typer.Option(
        ..., "--continuation-closeout", exists=True, file_okay=False
    ),
    output_dir: Path = typer.Option(..., "--output-dir"),
) -> None:
    """Assemble a stopped complete prefix and successful continuation without scoring."""

    result = assemble_qualification_composite(
        source_plan_path=source_plan_path,
        prefix_state_path=prefix_state_path,
        continuation_plan_path=continuation_plan_path,
        continuation_state_path=continuation_state_path,
        prefix_closeout_dir=prefix_closeout_dir,
        continuation_closeout_dir=continuation_closeout_dir,
        output_dir=output_dir,
    )
    console.print(json.dumps(result, ensure_ascii=False, indent=2))


@app.command("qualification-composite-lineage")
def qualification_composite_lineage_command(
    plan_paths: list[Path] = typer.Option(..., "--plan", exists=True),
    state_paths: list[Path] = typer.Option(..., "--state", exists=True),
    closeout_dirs: list[Path] = typer.Option(..., "--closeout", exists=True, file_okay=False),
    output_dir: Path = typer.Option(..., "--output-dir"),
) -> None:
    """Assemble exact-150 traces from two or more continuation segments."""

    result = assemble_qualification_lineage_composite(
        plan_paths=plan_paths,
        state_paths=state_paths,
        closeout_dirs=closeout_dirs,
        output_dir=output_dir,
    )
    console.print(json.dumps(result, ensure_ascii=False, indent=2))


@app.command("qualification-composite-replacements")
def qualification_composite_replacements_command(
    root_plan_path: Path = typer.Option(..., "--root-plan", exists=True),
    base_plan_paths: list[Path] = typer.Option(..., "--base-plan", exists=True),
    base_state_paths: list[Path] = typer.Option(..., "--base-state", exists=True),
    base_closeout_dirs: list[Path] = typer.Option(
        ..., "--base-closeout", exists=True, file_okay=False
    ),
    replacement_plan_path: Path = typer.Option(..., "--replacement-plan", exists=True),
    replacement_state_path: Path = typer.Option(..., "--replacement-state", exists=True),
    replacement_closeout_dir: Path = typer.Option(
        ..., "--replacement-closeout", exists=True, file_okay=False
    ),
    replacement_inventory_path: Path = typer.Option(..., "--replacement-inventory", exists=True),
    output_dir: Path = typer.Option(..., "--output-dir"),
) -> None:
    """Overlay separately authorized replacements onto an incomplete frozen lineage."""

    result = assemble_qualification_replacement_composite(
        root_plan_path=root_plan_path,
        base_plan_paths=base_plan_paths,
        base_state_paths=base_state_paths,
        base_closeout_dirs=base_closeout_dirs,
        replacement_plan_path=replacement_plan_path,
        replacement_state_path=replacement_state_path,
        replacement_closeout_dir=replacement_closeout_dir,
        replacement_inventory_path=replacement_inventory_path,
        output_dir=output_dir,
    )
    console.print(json.dumps(result, ensure_ascii=False, indent=2))


@app.command("qualification-score-composite")
def qualification_score_composite_command(
    composite_dir: Path = typer.Option(..., "--composite-dir", exists=True, file_okay=False),
    output_dir: Path = typer.Option(..., "--output-dir"),
) -> None:
    """Cross the correctness boundary only after exact-150 composite validation."""

    result = score_qualification_composite(composite_dir=composite_dir, output_dir=output_dir)
    console.print(json.dumps(result, ensure_ascii=False, indent=2))


@app.command("qualification-analyze")
def qualification_analyze_command(
    scoring_dir: Path = typer.Option(..., "--scoring-dir", exists=True, file_okay=False),
    config_path: Path = typer.Option(..., "--config", exists=True, readable=True),
    output_path: Path = typer.Option(..., "--output"),
) -> None:
    """Run the preregistered six-panel audit on an exact scored composite."""

    result = build_qualification_analysis(
        scoring_dir=scoring_dir,
        config_path=config_path,
        output_path=output_path,
    )
    console.print(json.dumps(result, ensure_ascii=False, indent=2))


@app.command("qualification-prepare-adjudication")
def qualification_prepare_adjudication_command(
    scoring_dir: Path = typer.Option(..., "--scoring-dir", exists=True, file_okay=False),
    output_dir: Path = typer.Option(..., "--output-dir"),
) -> None:
    """Create a hash-linked exact-150 input for blinded adjudication."""

    result = prepare_qualification_adjudication(scoring_dir=scoring_dir, output_dir=output_dir)
    console.print(json.dumps(result, ensure_ascii=False, indent=2))


@app.command("qualification-publish")
def qualification_publish_command(
    analysis_paths: list[Path] = typer.Option(..., "--analysis", exists=True, dir_okay=False),
    output_dir: Path = typer.Option(..., "--output-dir"),
) -> None:
    """Render hash-linked tables and figures from frozen six-panel analyses."""

    result = write_qualification_publication_bundle(
        output_dir=output_dir, analysis_paths=analysis_paths
    )
    console.print(json.dumps(result, ensure_ascii=False, indent=2))


@app.command("qualification-verify-public-analysis")
def qualification_verify_public_analysis_command(
    analysis_path: Path = typer.Option(
        ..., "--analysis", exists=True, dir_okay=False, readable=True
    ),
    config_path: Optional[Path] = typer.Option(
        None, "--config", exists=True, dir_okay=False, readable=True
    ),
) -> None:
    """Check a frozen analysis before aggregate-only public release."""

    result = verify_public_analysis_release(analysis_path, config_path=config_path)
    console.print(json.dumps(result, ensure_ascii=False, indent=2))


@app.command("qualification-verify-publication")
def qualification_verify_publication_command(
    bundle_dir: Path = typer.Option(
        ..., "--bundle-dir", exists=True, file_okay=False, readable=True
    ),
    analysis_paths: Optional[list[Path]] = typer.Option(
        None, "--analysis", exists=True, dir_okay=False, readable=True
    ),
) -> None:
    """Verify every registered table, figure, sidecar, and analysis input."""

    result = verify_qualification_publication_bundle(
        bundle_dir=bundle_dir, analysis_paths=analysis_paths or []
    )
    console.print(json.dumps(result, ensure_ascii=False, indent=2))


@app.command("qualification-reproduce-check")
def qualification_reproduce_check_command(
    analysis_paths: list[Path] = typer.Option(
        ..., "--analysis", exists=True, dir_okay=False, readable=True
    ),
    reference_dir: Path = typer.Option(
        ..., "--reference-dir", exists=True, file_okay=False, readable=True
    ),
) -> None:
    """Regenerate paper tables/figures and require byte-identical outputs."""

    result = reproduce_and_compare_qualification_publication(
        analysis_paths=analysis_paths, reference_dir=reference_dir
    )
    console.print(json.dumps(result, ensure_ascii=False, indent=2))


@app.command("qualification-freeze-adjudication")
def qualification_freeze_adjudication_command(
    scoring_dir: Path = typer.Option(..., "--scoring-dir", exists=True, file_okay=False),
    adjudication_input_dir: Path = typer.Option(
        ..., "--adjudication-input-dir", exists=True, file_okay=False
    ),
    adjudication_dir: Path = typer.Option(..., "--adjudication-dir", exists=True, file_okay=False),
    guide_file: Path = typer.Option(..., "--guide-file", exists=True, readable=True),
    guide_version: str = typer.Option("1.0"),
    output_dir: Path = typer.Option(..., "--output-dir"),
) -> None:
    """Freeze an exact-150 adjudicated sensitivity scoring set."""

    result = freeze_qualification_adjudication(
        scoring_dir=scoring_dir,
        adjudication_input_dir=adjudication_input_dir,
        adjudication_dir=adjudication_dir,
        output_dir=output_dir,
        guide_version=guide_version,
        guide_sha256=hashlib.sha256(guide_file.read_bytes()).hexdigest(),
    )
    console.print(json.dumps(result, ensure_ascii=False, indent=2))


@app.command("qualification-forecast")
def qualification_forecast_command(
    health_path: Path = typer.Option(..., "--health", exists=True),
    output_path: Path = typer.Option(..., "--output"),
    scenario: Optional[list[str]] = typer.Option(
        None,
        "--scenario",
        help="Repeat NAME=TASKS; defaults to M=200 and L=1000.",
    ),
) -> None:
    """Project optional future-study resource envelopes from blind telemetry."""

    scenarios = dict(DEFAULT_SCENARIOS)
    if scenario:
        scenarios = {}
        for value in scenario:
            if "=" not in value:
                raise typer.BadParameter("scenario must use NAME=TASKS")
            name, raw_tasks = value.split("=", 1)
            try:
                tasks = int(raw_tasks)
            except ValueError as exc:
                raise typer.BadParameter("scenario task count must be an integer") from exc
            scenarios[name] = tasks
    result = write_qualification_forecast(health_path, output_path, scenarios)
    console.print(json.dumps(result, ensure_ascii=False, indent=2))


@app.command("prepare-qualification-runs")
def prepare_qualification_runs_command(
    config_path: Path = typer.Option(..., "--config", exists=True, readable=True),
    authorization_path: Path = typer.Option(..., "--authorization", exists=True, readable=True),
    output_dir: Path = typer.Option(..., "--output-dir"),
) -> None:
    """Create three planned Q manifests from one approved, budgeted record."""

    manifest = prepare_qualification_run_manifests(config_path, authorization_path, output_dir)
    console.print(json.dumps(manifest, ensure_ascii=False, indent=2))


@app.command("initialize-qualification-ledger")
def initialize_qualification_ledger_command(
    authorization_path: Path = typer.Option(..., "--authorization", exists=True, readable=True),
    output_path: Path = typer.Option(..., "--output"),
) -> None:
    """Create a prompt-free hard-budget ledger from final authorization."""

    if output_path.exists():
        raise FileExistsError("budget-ledger output already exists: %s" % output_path)
    authorization = json.loads(authorization_path.read_text(encoding="utf-8"))
    ledger = initialize_budget_ledger(authorization)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    console.print(
        json.dumps(
            {
                "authorization_id": ledger["authorization_id"],
                "accounting_mode": ledger["accounting_mode"],
                "ledger_sha256": ledger["ledger_sha256"],
            },
            indent=2,
        )
    )


@app.command("compile-qualification-plan")
def compile_qualification_plan_command(
    bundle_manifest_path: Path = typer.Option(..., "--bundle-manifest", exists=True, readable=True),
    authorization_path: Path = typer.Option(..., "--authorization", exists=True, readable=True),
    output_path: Path = typer.Option(..., "--output"),
) -> None:
    """Compile the 150-episode blocked schedule without provider contact."""

    if output_path.exists():
        raise FileExistsError("execution-plan output already exists: %s" % output_path)
    bundle = json.loads(bundle_manifest_path.read_text(encoding="utf-8"))
    authorization = json.loads(authorization_path.read_text(encoding="utf-8"))
    plan = compile_qualification_execution_plan(bundle, authorization)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    console.print(
        json.dumps(
            {
                "plan_sha256": plan["plan_sha256"],
                "task_count": plan["task_count"],
                "episode_count": plan["episode_count"],
                "runnable": plan["runnable"],
            },
            indent=2,
        )
    )


@app.command("compile-qualification-continuation-plan")
def compile_qualification_continuation_plan_command(
    bundle_manifest_path: Path = typer.Option(..., "--bundle-manifest", exists=True, readable=True),
    authorization_path: Path = typer.Option(..., "--authorization", exists=True, readable=True),
    source_plan_path: Path = typer.Option(..., "--source-plan", exists=True, readable=True),
    source_state_path: Path = typer.Option(..., "--source-state", exists=True, readable=True),
    output_path: Path = typer.Option(..., "--output"),
) -> None:
    """Compile a failed-boundary rerun plus the remaining frozen suffix."""

    if output_path.exists():
        raise FileExistsError("execution-plan output already exists: %s" % output_path)
    bundle = json.loads(bundle_manifest_path.read_text(encoding="utf-8"))
    authorization = json.loads(authorization_path.read_text(encoding="utf-8"))
    source_plan = json.loads(source_plan_path.read_text(encoding="utf-8"))
    source_state = json.loads(source_state_path.read_text(encoding="utf-8"))
    plan = compile_qualification_continuation_plan(
        bundle,
        authorization,
        source_plan=source_plan,
        source_state=source_state,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    console.print(
        json.dumps(
            {
                "plan_sha256": plan["plan_sha256"],
                "task_count": plan["task_count"],
                "episode_count": plan["episode_count"],
                "restart_sequence": plan["continuation"]["restart_sequence"],
                "runnable": plan["runnable"],
            },
            indent=2,
        )
    )


@app.command("compile-qualification-replacement-plan")
def compile_qualification_replacement_plan_command(
    bundle_manifest_path: Path = typer.Option(..., "--bundle-manifest", exists=True, readable=True),
    authorization_path: Path = typer.Option(..., "--authorization", exists=True, readable=True),
    source_plan_path: Path = typer.Option(..., "--source-plan", exists=True, readable=True),
    replacement_inventory_path: Path = typer.Option(
        ..., "--replacement-inventory", exists=True, readable=True
    ),
    output_path: Path = typer.Option(..., "--output"),
) -> None:
    """Compile the frozen exact-slot replacement schedule without provider contact."""

    if output_path.exists():
        raise FileExistsError("execution-plan output already exists: %s" % output_path)
    bundle = json.loads(bundle_manifest_path.read_text(encoding="utf-8"))
    authorization = json.loads(authorization_path.read_text(encoding="utf-8"))
    source_plan = json.loads(source_plan_path.read_text(encoding="utf-8"))
    inventory = json.loads(replacement_inventory_path.read_text(encoding="utf-8"))
    plan = compile_qualification_replacement_plan(
        bundle,
        authorization,
        source_plan=source_plan,
        replacement_inventory=inventory,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    console.print(
        json.dumps(
            {
                "plan_sha256": plan["plan_sha256"],
                "task_count": plan["task_count"],
                "episode_count": plan["episode_count"],
                "replacement_sequences": plan["replacement"]["replacement_sequences"],
                "runnable": plan["runnable"],
            },
            indent=2,
        )
    )


@app.command("verify-qualification-plan")
def verify_qualification_plan_command(
    plan_path: Path = typer.Argument(..., exists=True, readable=True),
    bundle_manifest_path: Path = typer.Option(..., "--bundle-manifest", exists=True, readable=True),
    authorization_path: Path = typer.Option(..., "--authorization", exists=True, readable=True),
    source_plan_path: Optional[Path] = typer.Option(
        None, "--source-plan", exists=True, readable=True
    ),
    source_state_path: Optional[Path] = typer.Option(
        None, "--source-state", exists=True, readable=True
    ),
    replacement_inventory_path: Optional[Path] = typer.Option(
        None, "--replacement-inventory", exists=True, readable=True
    ),
) -> None:
    """Verify that an execution plan is an exact deterministic compilation."""

    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    bundle = json.loads(bundle_manifest_path.read_text(encoding="utf-8"))
    authorization = json.loads(authorization_path.read_text(encoding="utf-8"))
    if replacement_inventory_path is None:
        if (source_plan_path is None) != (source_state_path is None):
            raise typer.BadParameter("--source-plan and --source-state must be supplied together")
    elif source_plan_path is None or source_state_path is not None:
        raise typer.BadParameter(
            "replacement verification requires --source-plan and --replacement-inventory only"
        )
    source_plan = (
        json.loads(source_plan_path.read_text(encoding="utf-8"))
        if source_plan_path is not None
        else None
    )
    source_state = (
        json.loads(source_state_path.read_text(encoding="utf-8"))
        if source_state_path is not None
        else None
    )
    replacement_inventory = (
        json.loads(replacement_inventory_path.read_text(encoding="utf-8"))
        if replacement_inventory_path is not None
        else None
    )
    verify_kwargs = {"source_plan": source_plan, "source_state": source_state}
    if replacement_inventory is not None:
        verify_kwargs["replacement_inventory"] = replacement_inventory
    console.print(
        json.dumps(
            verify_qualification_execution_plan(plan, bundle, authorization, **verify_kwargs),
            indent=2,
        )
    )


@app.command("score")
def score_command(
    input_path: Path = typer.Argument(..., exists=True, readable=True),
    output_path: Path = typer.Option(..., "--output"),
) -> None:
    """Apply the conservative deterministic scorer to canonical evidence."""

    episodes = [score_episode(episode) for episode in read_episodes(input_path)]
    write_episodes(output_path, episodes)
    label_counts = {}
    for episode in episodes:
        for label in episode.labels:
            label_counts[label.value.value] = label_counts.get(label.value.value, 0) + 1
    console.print(json.dumps({"episodes": len(episodes), "labels": label_counts}, indent=2))


@app.command("adjudication-export")
def adjudication_export_command(
    input_path: Path = typer.Option(..., "--input", exists=True, readable=True),
    output_dir: Path = typer.Option(..., "--output-dir"),
    blinding_key_file: Path = typer.Option(..., "--blinding-key-file", exists=True, readable=True),
    guide_file: Path = typer.Option(..., "--guide-file", exists=True, readable=True),
    audit_sample_size: int = typer.Option(50, min=0),
    minimum_item_count: int = typer.Option(1, min=1),
    guide_version: str = typer.Option("1.0"),
    order_seed: int = typer.Option(20260823),
) -> None:
    """Export private linkage and two independently ordered blinded rater files."""

    manifest = export_adjudication_bundle(
        output_dir,
        read_episodes(input_path),
        blinding_key=blinding_key_file.read_text(encoding="utf-8").strip(),
        guide_sha256=hashlib.sha256(guide_file.read_bytes()).hexdigest(),
        audit_sample_size=audit_sample_size,
        minimum_item_count=minimum_item_count,
        guide_version=guide_version,
        order_seed=order_seed,
    )
    console.print(json.dumps(manifest, ensure_ascii=False, indent=2))


@app.command("adjudication-agreement")
def adjudication_agreement_command(
    rater_a_path: Path = typer.Option(..., "--rater-a", exists=True, readable=True),
    rater_b_path: Path = typer.Option(..., "--rater-b", exists=True, readable=True),
    output_dir: Path = typer.Option(..., "--output-dir"),
) -> None:
    """Measure pre-discussion agreement and create the blinded third-pass queue."""

    report = agreement_and_conflicts(output_dir, rater_a_path, rater_b_path)
    console.print(json.dumps(report, ensure_ascii=False, indent=2))


@app.command("adjudication-apply")
def adjudication_apply_command(
    input_path: Path = typer.Option(..., "--input", exists=True, readable=True),
    linkage_path: Path = typer.Option(..., "--linkage", exists=True, readable=True),
    rater_a_path: Path = typer.Option(..., "--rater-a", exists=True, readable=True),
    rater_b_path: Path = typer.Option(..., "--rater-b", exists=True, readable=True),
    output_dir: Path = typer.Option(..., "--output-dir"),
    third_pass_path: Optional[Path] = typer.Option(
        None, "--third-pass", exists=True, readable=True
    ),
    guide_file: Path = typer.Option(..., "--guide-file", exists=True, readable=True),
    guide_version: str = typer.Option("1.0"),
) -> None:
    """Append frozen human and consensus labels without altering prior scorer labels."""

    manifest = apply_adjudication(
        output_dir,
        read_episodes(input_path),
        linkage_path,
        rater_a_path,
        rater_b_path,
        third_pass_path=third_pass_path,
        guide_version=guide_version,
        guide_sha256=hashlib.sha256(guide_file.read_bytes()).hexdigest(),
    )
    console.print(json.dumps(manifest, ensure_ascii=False, indent=2))


@app.command("audit")
def audit_command(
    input_path: Path = typer.Argument(..., exists=True, readable=True),
    source_a: str = typer.Option(...),
    source_b: str = typer.Option(...),
    output_path: Optional[Path] = typer.Option(None, "--output"),
    bootstrap_replicates: int = typer.Option(1000, min=0),
    seed: int = typer.Option(20260822),
) -> None:
    """Run a two-source dependence, co-failure, and transition audit."""

    episodes = list(read_episodes(input_path))
    report = {
        "availability": [
            availability_profile(episodes, source_a),
            availability_profile(episodes, source_b),
        ],
        "pairwise": pairwise_dependence(
            episodes,
            source_a,
            source_b,
            bootstrap_replicates=bootstrap_replicates,
            seed=seed,
        ),
        "cofailure": cofailure(episodes, [source_a, source_b]),
        "transitions": transition_metrics(episodes, source_a, source_b),
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if output_path is None:
        console.print(rendered)
    else:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered + "\n", encoding="utf-8")
        console.print("Wrote %s" % output_path)


@app.command("report")
def report_command(
    input_path: Path = typer.Argument(..., exists=True, readable=True),
    output_dir: Path = typer.Option(..., "--output-dir"),
    pair: Optional[list[str]] = typer.Option(
        None, "--pair", help="Repeat as --pair source_a,source_b. Defaults to all upstream pairs."
    ),
    bootstrap_replicates: int = typer.Option(1000, min=0),
    seed: int = typer.Option(20260822),
) -> None:
    """Generate report.json, manifest.json, and a standalone HTML report."""

    pairs = None
    if pair:
        pairs = []
        for value in pair:
            parts = [part.strip() for part in value.split(",")]
            if len(parts) != 2 or not all(parts):
                raise typer.BadParameter("pair must be source_a,source_b")
            pairs.append((parts[0], parts[1]))
    manifest = write_report(
        output_dir,
        read_episodes(input_path),
        pairs=pairs,
        bootstrap_replicates=bootstrap_replicates,
        seed=seed,
    )
    console.print(json.dumps(manifest, ensure_ascii=False, indent=2))


@app.command("export-parquet")
def export_parquet_command(
    input_path: Path = typer.Argument(..., exists=True, readable=True),
    output_dir: Path = typer.Option(..., "--output-dir"),
) -> None:
    """Export normalized canonical tables using the optional Parquet dependency."""

    from .parquet import write_parquet_bundle

    paths = write_parquet_bundle(output_dir, read_episodes(input_path))
    console.print(json.dumps({"files": [str(path) for path in paths]}, indent=2))


@app.command("publish")
def publish_command(
    input_path: Path = typer.Option(..., "--input", exists=True, readable=True),
    config_path: Path = typer.Option(..., "--config", exists=True, readable=True),
    output_dir: Path = typer.Option(..., "--output-dir"),
) -> None:
    """Generate preregistered paper tables, SVG figures, and hash manifests."""

    from .publication import write_publication_bundle

    config = json.loads(config_path.read_text(encoding="utf-8"))
    manifest = write_publication_bundle(output_dir, read_episodes(input_path), config)
    console.print(json.dumps(manifest, ensure_ascii=False, indent=2))


@app.command("sample")
def sample_command(
    input_path: Path = typer.Option(..., "--input", exists=True, readable=True),
    private_output: Path = typer.Option(..., "--private-output"),
    public_manifest: Path = typer.Option(..., "--public-manifest"),
    dataset_id: str = typer.Option(...),
    dataset_version: Optional[str] = typer.Option(None),
    stratum: str = typer.Option(...),
    count: int = typer.Option(..., min=1),
    seed: int = typer.Option(20260823),
    statement_field: str = typer.Option("problem"),
    id_field: Optional[str] = typer.Option(None),
    difficulty_field: Optional[str] = typer.Option(None),
    difficulty_gt: Optional[float] = typer.Option(None),
    difficulty_le: Optional[float] = typer.Option(None),
    balance_field: Optional[str] = typer.Option(None),
    balance_depth: Optional[int] = typer.Option(None, min=1),
    balance_mode: str = typer.Option("equal"),
) -> None:
    """Create a private task sample and a text-free public ID/hash manifest."""

    records = [payload for payload, _ in iter_payloads(input_path)]
    config = {
        "count": count,
        "statement_field": statement_field,
        "id_field": id_field,
        "difficulty_field": difficulty_field,
        "difficulty_gt": difficulty_gt,
        "difficulty_le": difficulty_le,
        "balance_field": balance_field,
        "balance_depth": balance_depth,
        "balance_mode": balance_mode,
        "duplicate_problem_policy": "exclude_all_records_in_duplicate_problem_groups",
    }
    selected, diagnostics = select_sample(
        records,
        dataset_id=dataset_id,
        count=count,
        seed=seed,
        statement_field=statement_field,
        id_field=id_field,
        difficulty_field=difficulty_field,
        difficulty_gt=difficulty_gt,
        difficulty_le=difficulty_le,
        balance_field=balance_field,
        balance_depth=balance_depth,
        balance_mode=balance_mode,
    )
    private_output.parent.mkdir(parents=True, exist_ok=True)
    with private_output.open("w", encoding="utf-8") as handle:
        for item in selected:
            payload = dict(item.record)
            payload["_mathaudit"] = {
                "problem_sha256": item.problem_hash,
                "record_sha256": item.record_hash,
                "balance_group": item.balance_group,
            }
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
    manifest = public_sample_manifest(
        selected,
        source_path=input_path,
        dataset_id=dataset_id,
        dataset_version=dataset_version,
        stratum=stratum,
        seed=seed,
        selection_config=config,
        diagnostics=diagnostics,
    )
    public_manifest.parent.mkdir(parents=True, exist_ok=True)
    public_manifest.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    console.print(
        json.dumps(
            {
                "selected": len(selected),
                "private_output": str(private_output),
                "public_manifest": str(public_manifest),
                "manifest_sha256": manifest["manifest_sha256"],
                "diagnostics": diagnostics,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


@app.command("validate-json")
def validate_json_command(
    input_path: Path = typer.Argument(..., exists=True, readable=True),
    schema_path: Path = typer.Option(..., "--schema", exists=True, readable=True),
) -> None:
    """Validate a JSON object, array, or JSONL stream against a JSON Schema."""

    try:
        from jsonschema import Draft202012Validator
    except ImportError as exc:
        raise RuntimeError(
            "JSON Schema validation requires the 'schema' extra: "
            "pip install 'math-harness-audit[schema]'"
        ) from exc

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    documents = 0
    errors = 0
    for payload, locator in iter_payloads(input_path):
        documents += 1
        for issue in sorted(validator.iter_errors(payload), key=lambda item: list(item.path)):
            errors += 1
            path = ".".join(str(part) for part in issue.path) or "$"
            console.print("[ERROR] %s %s: %s" % (locator, path, issue.message))
    if errors:
        raise typer.Exit(code=1)
    console.print("Validated %d JSON document(s) against %s." % (documents, schema_path.name))


@app.command("verify-sample-manifest")
def verify_sample_manifest_command(
    input_path: Path = typer.Argument(..., exists=True, readable=True),
) -> None:
    """Verify a public sample manifest's embedded canonical JSON self-hash."""

    manifest = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("format") != "mathaudit-sample-manifest-v0.1":
        console.print("[ERROR] not a mathaudit-sample-manifest-v0.1 object")
        raise typer.Exit(code=1)
    if not verify_sample_manifest_hash(manifest):
        console.print("[ERROR] manifest_sha256 does not match the manifest content")
        raise typer.Exit(code=1)
    console.print("Verified sample manifest self-hash: %s" % manifest["manifest_sha256"])


@app.command("prepare-run-inputs")
def prepare_run_inputs_command(
    private_samples: list[Path] = typer.Option(..., "--private-sample", exists=True, readable=True),
    public_manifests: list[Path] = typer.Option(
        ..., "--public-manifest", exists=True, readable=True
    ),
    output_dir: Path = typer.Option(..., "--output-dir"),
    system_ids: list[str] = typer.Option(..., "--system-id"),
    schedule_seed: int = typer.Option(20260823),
) -> None:
    """Compile gold-separated inputs and a deterministic matched-task schedule."""

    bundle = prepare_matched_run_inputs(
        private_samples=private_samples,
        public_manifests=public_manifests,
        output_dir=output_dir,
        system_ids=system_ids,
        schedule_seed=schedule_seed,
    )
    console.print(
        json.dumps(
            {
                "task_count": bundle["task_count"],
                "output_dir": str(output_dir),
                "bundle_sha256": bundle["bundle_sha256"],
            },
            indent=2,
        )
    )


@app.command("verify-input-bundle")
def verify_input_bundle_command(
    input_dir: Path = typer.Argument(..., exists=True, file_okay=False, readable=True),
) -> None:
    """Verify a prepared matched-run input bundle and its gold separation."""

    console.print(json.dumps(verify_input_bundle(input_dir), indent=2))


if __name__ == "__main__":
    app()
