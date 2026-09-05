# Submission-readiness audit: MathHarnessAudit 0.2.1

Audit date: 2026-09-05

Target: Elsevier SoftwareX Original Software Publication

Evidence policy: no scientific claim is treated as closed unless it resolves to
source data, an analysis configuration, executable code, a generated artifact,
and a manuscript marker or statement.

## Executive decision

All internally remediable blockers identified in the repository review are
closed in the 0.2.1 candidate. The most likely first-round editorial outcome is
**Minor Revision**, not direct acceptance. A **Major Revision** remains plausible
if a reviewer requires redistributable row-level traces rather than accepting
the explicitly limited aggregate-analysis-to-artifact reproduction boundary.
The package is suitable for submission once the immutable tag/release gate has
passed and the authors approve the exact uploaded files.

## Closed findings

### P0 — undefined bootstrap resamples were hidden

- Original risk: percentile endpoints were calculated after silently dropping
  resamples in which a binary marginal had zero variance. Calling the result a
  generic 95% interval overstated its interpretation.
- Fix: both exact-source and source-type dependence outputs now expose requested,
  defined, and undefined replicate counts, the defined fraction, conditioning,
  interval status, quantiles, and an explicit `nominal_coverage_established:
  false` field. The legacy endpoint field remains for compatibility, but the
  documentation and manuscript call it a 2.5--97.5 percentile range conditional
  on defined resamples.
- Files: `src/mathaudit/metrics.py`, `src/mathaudit/publication.py`,
  `src/mathaudit/qualification_publication.py`,
  `src/mathaudit/qualification_analysis.py`, `docs/statistical_contract.md`,
  `tests/test_metrics.py`, `tests/test_qualification_composite.py`.
- Verification: targeted tests cover partially undefined, entirely undefined,
  zero-request, and deterministic-repeat cases. The full suite passes.

### P0 — manuscript claims and generated artifacts could drift

- Original risk: narrative numbers were not sufficient proof of their own
  analytical lineage.
- Fix: the 150-episode aggregate snapshot was regenerated with the corrected
  statistic, the full publication bundle was regenerated, and the claim ledger
  was rebound to the new analysis hash and bootstrap defined/undefined counts.
  Analysis JSON is written with explicit LF newlines so its raw input hash and
  publication manifest are stable across Windows and Linux checkouts.
- Files: `paper/data/analysis-deterministic-q14-v1.json`,
  `paper/results/deterministic-q14-v1/`, `paper/claim-ledger.json`,
  `paper/verify_claims.py`, `paper/softwarex.tex`.
- Verification: the public-analysis validator reports 150 episodes in six
  panels; publication verification checks 19 registered artifacts; reproduction
  regenerates 20 files byte-identically; seven manuscript claim groups resolve
  to unique CSV selectors and LaTeX markers.

### P1 — mutable or inconsistent release identity

- Original risk: 0.2.0 metadata pointed to a mutable repository root, and its
  immutable tag retained a failed Linux workflow. Rewriting that tag would have
  damaged provenance.
- Fix: the package, lock file, citation metadata, README, documentation,
  manuscript metadata C1/C2/C7, generated manifests, and distribution filenames
  now target 0.2.1. The permanent code link is the immutable `v0.2.1` tree. The
  0.2.0 history remains unchanged and is documented in the changelog.
- Files: `pyproject.toml`, `uv.lock`, `src/mathaudit/__init__.py`,
  `CITATION.cff`, `CHANGELOG.md`, `README.md`, `docs/`, `paper/softwarex.tex`.
- Verification: package import and wheel metadata both report 0.2.1. The release
  process publishes only after the exact tagged workflow passes.

### P1 — software quality and clean-install evidence

- Fix: the public suite was expanded with bootstrap failure-mode tests; lint and
  formatting gates cover source, tests, examples, and paper utilities. Source
  and universal-wheel distributions build from the locked environment.
- Verification: 168 tests pass; Ruff lint and format checks pass; a clean Python
  3.12 environment installs the wheel, reports version 0.2.1, lists schemas, and
  completes the provider-free fixture. Dependency audit reports no known
  vulnerability in third-party dependencies (the local project itself is not a
  PyPI-resolved dependency).

### P1 — figures obscured architecture and interface boundaries

- Original risk: text was too small and optional acquisition governance competed
  with the core audit path.
- Fix: Figure 1 now separates native inputs, fidelity-aware adaptation,
  canonical episodes, deterministic scoring, and audit/publication; the
  reference answer crosses an explicit audit-only boundary. Figure 2 shows the
  provider-free core path and optional sibling exports without implying model
  performance.
- Files: `paper/figures/software_architecture.{svg,png}` and
  `paper/figures/five_minute_workflow.{svg,png}`.
- Verification: both SVGs contain accessible title/description elements; the
  raster versions and final A4 PDF were visually inspected at page resolution.

### P1 — manuscript overstatement and ambiguous denominators

- Fix: system ranking and architecture-causality remain disabled. Availability,
  complete-case co-failure, operational no-correct-support, repair/harm
  opportunities, proxy utilization, and exact text repetition are kept as
  distinct estimands. Sparse cells and every undefined bootstrap draw remain
  visible. The three reported dependence ranges explicitly state their defined
  counts and lack of asserted nominal coverage.
- Files: `paper/softwarex.tex`, `paper/experiment-validation.md`,
  `docs/statistical_contract.md`.
- Verification: all reported values are covered by the claim ledger or by
  generated aggregate tables; the manuscript makes no p-value, causal, or
  universal-correlation claim.

### P1 — submission and release artifacts were assembled manually

- Fix: the source manifest hashes the public software, tests, documentation, and
  paper inputs after normalizing text line endings. A deterministic archive
  builder refuses a stale manifest and bundles the exact sources, manifest, and
  compiled PDF under a fixed archive root and timestamp. LaTeX intermediates and
  the locally compiled convenience PDF are explicitly excluded from source-input
  discovery, so a clean checkout and an authoring workspace have the same scope.
- Files: `paper/build_submission_manifest.py`,
  `paper/build_submission_archive.py`, `paper/README.md`.
- Verification: manifest verification rejects any later source drift; ZIP CRC
  verification runs inside the archive builder.

## Intentionally constrained evidence

- The public audit input is text-free and aggregate. It is sufficient to
  regenerate the paper tables and figures, but it cannot repeat provider calls
  or rescore restricted benchmark answers. The manuscript states this boundary
  rather than calling it full raw-run reproducibility.
- Private prompts, responses, request identifiers, credentials, benchmark rows,
  linkage, human rationales, and development-only human/reuse records are not
  included. Human-derived agreement or reuse claims are not used in the paper.
- The 150 episodes form a descriptive reference audit. Unequal observability and
  sparse complete-case cells prohibit system ranking and causal architecture
  conclusions.

## External blockers not fabricated

1. No Zenodo or other archival DOI has been minted. The manuscript asserts only
   the immutable GitHub tag and does not contain a placeholder DOI.
2. The authors must inspect and approve the exact final manuscript, declarations,
   author metadata, and uploaded release/submission assets.
3. Redistribution of raw provider traces or benchmark text would require rights
   and privacy review outside the repository. No such permission is inferred.
4. Any future use of private human-rating or independent-reuse records requires
   the applicable institutional determination; those records are excluded here.

## Residual review risks

- A reviewer may prefer a larger, prospectively powered audit or more independent
  harnesses. Adding episodes solely to improve results would violate the frozen
  design; the paper therefore presents the audit as descriptive validation.
- A reviewer may consider aggregate-only reproduction insufficient despite the
  restricted-data rationale. The appropriate response is to provide a lawful
  controlled-access route or a separately authorized de-identified row-level
  release, not to imply that such data are already public.
- The generic OpenTelemetry bridge is deliberately conservative and cannot infer
  unrecorded topology. This is an interface boundary, not universal plug-and-play
  support.

## Final readiness judgment

**Minor Revision most likely.** The software object, deterministic tests,
versioned interface, statistical definitions, generated artifacts, and claim
lineage are internally coherent and reproducible at the stated public boundary.
Direct acceptance is unlikely for a first submission, while rejection is no
longer the leading outcome. The main remaining uncertainty is reviewer policy
on aggregate-only evidence and the descriptive scale of the reference audit,
not an unresolved internal correctness or provenance defect.
