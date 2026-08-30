# MathHarnessAudit / AdaMathRouter

[![CI](https://github.com/abaiar/MathHarnessAudit/actions/workflows/ci.yml/badge.svg)](https://github.com/abaiar/MathHarnessAudit/actions/workflows/ci.yml)

This repository is being organized around two deliberately separate research
outputs:

- **MathHarnessAudit**: reusable software for outcome-linked evidence auditing
  of mathematical reasoning agents. This is the planned SoftwareX paper.
- **AdaMathRouter**: a later method paper on module attribution and adaptive
  orchestration, built on the audit data produced by MathHarnessAudit.

Private research notebooks, raw traces, evaluated-system checkouts, API
credentials, and publisher templates are maintained outside this public source
distribution.

Current status: public pre-alpha software candidate. The package, schemas,
examples, tests, adapter documentation, and CI workflow are included here;
research-specific audit records are intentionally kept in a separate private
workspace.

## Current software prototype

The repository now contains an installable pre-alpha package with:

- canonical outcome-linked evidence, source-availability, decision, provenance,
  cost, and scoring-label models;
- ICMA, MathRouterAgent (Hermes-based), MathGoal, canonical JSON, and conservative
  OpenTelemetry bridges;
- deterministic-first mathematical answer scoring;
- blinded double-rater adjudication with agreement measurement, third-pass
  conflict resolution, content-hash checks, and append-only frozen labels;
- availability, dependence, co-failure, provenance-support, repair/harm, and cost
  primitives;
- JSONL ingestion/validation and static HTML audit reports.
- deterministic outcome-blind sampling with text-free, self-hashed public
  manifests and strict run/deviation/sample JSON Schemas.
- preregistered system-by-stratum publication panels that generate deterministic
  CSV tables, accessible SVG figures, exact intervals, figure sidecars, and a
  content-hashed publication manifest.
- cross-platform source-tree fingerprints with explicit file inventories,
  self-hashes, and drift detection for non-Git reference snapshots.

The canonical episode contract is frozen as Schema v1.0 with an explicit,
lossless v0.1 migration path. Historical qualification formats retain their
recorded versions. Pilot outputs remain exploratory and must not replace the
frozen exact-150 results.

## Reproduce the fixture demo

With [uv](https://docs.astral.sh/uv/) installed:

```powershell
uv run --extra dev python examples/run_demo.py --output-dir tmp/fixture-demo
```

The command ingests a synthetic ICMA-shaped trace, validates the canonical
episode, applies the deterministic scorer, and writes `report.json`,
`manifest.json`, and a standalone `index.html`.

Run the software checks:

```powershell
uv run --extra dev ruff check src tests
uv run --all-extras pytest --cov=mathaudit
uv build
```

CLI overview:

```powershell
uv run mathaudit --help
```

Key reproducibility commands include `mathaudit sample`,
`mathaudit verify-sample-manifest`, `mathaudit prepare-run-inputs`,
`mathaudit verify-input-bundle`, and `mathaudit validate-json`. They separate
private benchmark rows, solver-visible questions, audit-only gold, and public
ID/hash manifests before a model run begins.
`mathaudit fingerprint-source`/`verify-source-fingerprint` freeze non-Git source
trees without locale-dependent ordering. `mathaudit
verify-qualification-authorization`, `prepare-qualification-runs`,
`compile-qualification-plan`, and `qualification-preflight` make provider
contact impossible to authorize with a pending budget record or mismatched
source/sample/run manifests. Plan compilation materializes the exact 150-row
task-major blocked schedule without contacting a provider and keeps pending
authorizations explicitly non-runnable; `verify-qualification-plan` rejects any
hand edit or authorization/bundle drift.
`initialize-qualification-ledger` creates a self-hashed, prompt-free resource
ledger only from a final semantically valid authorization. Request accounting
reserves conservative input/output token and monetary upper bounds before
network contact, so a nominal cap cannot be exceeded and explained afterward.
`mathaudit publish` is the only supported route from scored canonical episodes
to paper-facing empirical tables and figures; it refuses unregistered/missing
panels and nonempty output directories.
The human-scoring route is deliberately staged as `mathaudit
adjudication-export`, `mathaudit adjudication-agreement`, and `mathaudit
adjudication-apply`; public rater files never contain system/source identities or
the deterministic proposed label.

Machine-readable contracts are in
[`schemas/`](schemas/), including episode, public-sample, run-manifest,
deviation-event, publication-configuration, and source-fingerprint schemas.

Reusable documentation includes the
[`adapter tutorial`](docs/writing_an_adapter.md),
[`v1.0 migration guide`](docs/migrating_to_v1.md),
[`compatibility policy`](docs/compatibility.md), and
[`troubleshooting guide`](docs/troubleshooting.md). Contribution and conduct
expectations are in [`CONTRIBUTING.md`](CONTRIBUTING.md) and
[`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md).
