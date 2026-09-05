# MathHarnessAudit

[![CI](https://github.com/abaiar/MathHarnessAudit/actions/workflows/ci.yml/badge.svg)](https://github.com/abaiar/MathHarnessAudit/actions/workflows/ci.yml)

MathHarnessAudit is reusable software for outcome-linked evidence auditing of
mathematical reasoning agents. It is deliberately separate from AdaMathRouter,
a later method project on adaptive orchestration.

Private research notebooks, raw traces, evaluated-system checkouts, API
credentials, and publisher templates are maintained outside this public source
distribution.

Current status: **v0.2.2 SoftwareX submission candidate**. The public repository
contains the package, schemas, examples, tests, adapter documentation, CI, and a
text-free analysis snapshot that regenerates the paper's reference-audit tables
and figures. Restricted benchmark text, model responses, credentials, and
person-linkable research records remain outside the public distribution.

## Install

From a source checkout:

```powershell
python -m pip install -e ".[schema]"
mathaudit --help
```

For a locked contributor environment with [uv](https://docs.astral.sh/uv/):

```powershell
uv sync --locked --all-extras
uv run mathaudit --help
```

## Software capabilities

The installable package provides:

- canonical outcome-linked evidence, source-availability, decision, provenance,
  cost, and scoring-label models;
- ICMA, MathRouterAgent (Hermes-based), MathGoal, canonical JSON, and conservative
  OpenTelemetry bridges;
- deterministic-first mathematical answer scoring;
- an optional blinded adjudication workflow with agreement measurement,
  third-pass conflict resolution, content-hash checks, and append-only frozen
  labels;
- availability, dependence, co-failure, provenance-support, repair/harm, and cost
  primitives;
- JSONL ingestion/validation and static HTML audit reports;
- deterministic outcome-blind sampling with text-free, self-hashed public
  manifests and strict run/deviation/sample JSON Schemas;
- preregistered system-by-stratum publication panels that generate deterministic
  CSV tables, accessible SVG figures, exact intervals, figure sidecars, and a
  content-hashed publication manifest;
- cross-platform source-tree fingerprints with explicit file inventories,
  self-hashes, and drift detection for non-Git reference snapshots.

The canonical episode contract is frozen as Schema v1.0 with an explicit,
lossless v0.1 migration path. Historical qualification formats retain their
recorded versions. Pilot outputs remain exploratory and must not replace the
frozen exact-150 results.

## Reproduce the paper audit

The committed input is an aggregate, self-hashed analysis snapshot. It contains
no prompt, response, gold-answer, rationale, credential, request identifier, or
local absolute path. The following commands validate that boundary and require
every regenerated CSV, SVG, sidecar, and manifest to be byte-identical to the
committed reference bundle:

```powershell
uv run --frozen mathaudit qualification-verify-public-analysis `
  --analysis paper/data/analysis-deterministic-q14-v1.json `
  --config paper/config/qualification-analysis-config-v0.1.json

uv run --frozen mathaudit qualification-verify-publication `
  --bundle-dir paper/results/deterministic-q14-v1 `
  --analysis paper/data/analysis-deterministic-q14-v1.json

uv run --frozen mathaudit qualification-reproduce-check `
  --analysis paper/data/analysis-deterministic-q14-v1.json `
  --reference-dir paper/results/deterministic-q14-v1

uv run --frozen python paper/verify_claims.py
uv run --frozen python paper/build_submission_manifest.py
```

This path reproduces the reported analysis artifacts; it does **not** recreate
provider calls or deterministic scoring from restricted benchmark rows and
private model traces. The exact boundary and field definitions are documented
in [`paper/README.md`](paper/README.md) and
[`docs/statistical_contract.md`](docs/statistical_contract.md).

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
Installed wheels embed the same contracts. Use `mathaudit list-schemas` to inspect
them or `mathaudit export-schemas --output-dir <empty-directory>` to obtain ordinary
JSON files without locating interpreter-specific data directories.

Reusable documentation includes the
[`adapter tutorial`](docs/writing_an_adapter.md),
[`v1.0 migration guide`](docs/migrating_to_v1.md),
[`compatibility policy`](docs/compatibility.md), and
[`troubleshooting guide`](docs/troubleshooting.md). Contribution and conduct
expectations are in [`CONTRIBUTING.md`](CONTRIBUTING.md) and
[`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md).
