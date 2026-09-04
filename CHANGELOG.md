# Changelog

All notable changes to MathHarnessAudit will be documented here.

## 0.2.0 - unreleased submission candidate

- Added a public, text-free frozen analysis snapshot and a documented clean
  reproduction path for all reference-audit CSV tables and SVG figures.
- Added release-boundary validation that rejects raw prompt/answer fields,
  request identifiers, secret-shaped values, and local absolute paths from an
  aggregate analysis export.
- Added publication-bundle verification and byte-for-byte regeneration checks
  for tables, figures, sidecars, input identities, and self-hashed manifests.
- Added a machine-checkable claim ledger linking manuscript numbers to frozen
  analysis rows and generated artifacts.
- Clarified the episode-balanced source-type dependence estimator, missingness
  denominators, precision flag, and aggregate-only re-execution boundary.
- Removed unresolved human-rating and participant-reuse results from the
  submission evidence base; retained them privately as non-paper-eligible
  research records pending external governance resolution.
- Aligned package metadata, README, CI, manuscript, and source release around a
  single v0.2.0 release candidate.

## 0.1.0 - 2026-09-01

- Embedded all 41 public JSON Schemas inside the wheel, added deterministic
  `list-schemas` and refuse-merge `export-schemas` CLI commands, and removed the
  Windows deep-path-sensitive `data_files` installation layout.
- Froze the canonical episode Schema as v1.0, retained explicit v0.1 reading,
  and added a lossless, refuse-overwrite `migrate-episode-v1` CLI path with
  compatibility tests for every public v0.1 fixture.
- Established the v0.1 canonical evidence/provenance contract.
- Added ICMA, MathRouterAgent, MathGoal, canonical JSON, and conservative OTel
  adapters.
- Added deterministic-first answer scoring with exact, rational-numeric, and
  restricted AST-based symbolic equivalence.
- Added availability, pairwise dependence, joint co-failure, provenance support,
  repair/harm transition, and effective-support analyses.
- Added canonical validation, JSONL I/O, CLI commands, machine-readable bundles,
  static HTML reports, synthetic fixtures, and metric oracle tests.
- Added deterministic duplicate-safe benchmark sampling, identifier-only
  self-hashed public manifests, and strict sample/run/deviation JSON Schemas.
- Added CLI verification for sample self-hashes and general Draft 2020-12 JSON
  Schema validation.
- Added deterministic matched-task scheduling and gold-separated run-input
  bundles with self-hash, file-hash, row-join, and solver-field verification.
- Added exact binomial intervals and a deterministic preregistered publication
  pipeline for system-by-stratum CSV tables, accessible SVGs, figure sidecars,
  and content-hashed manifests.
- Stabilized MathGoal full-trace source identities by candidate role, preserved
  candidate IDs as metadata, and represented uncalled tools explicitly.
- Added deterministic blinded adjudication export, independently ordered rater
  templates, pre-discussion raw agreement/Cohen's kappa, exact third-pass
  conflict queues, content-hash verification, and append-only frozen labels.
- Added explicit source-tree inventories and a locale-independent UTF-8 path
  ordering algorithm, correcting the portability gap in legacy PowerShell-sorted
  ICMA/MathGoal snapshot hashes without discarding the historical values.
- Added machine-readable Q compute authorization with total and per-system hard
  caps, deterministic planned-run manifest generation, and a fail-closed
  provider-free preflight over sources, samples, gold separation, dependency
  lock, runner, authorization, and exact run-manifest set.
- Added a stable adapter-authoring tutorial, compatibility/deprecation policy,
  troubleshooting guide, contribution/conduct guidance, and structured adapter
  request/trace-bug issue templates.
