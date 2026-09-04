# Submission-readiness audit: MathHarnessAudit 0.2.0 candidate

Audit date: 2026-09-04
Target: Elsevier SoftwareX Original Software Publication
Scope: public source tree, tests, package metadata, paper bundle, manuscript,
and locally built release/submission artifacts

## Decision

**Current submission-state decision: Major Revision.** The internal software and
aggregate-analysis blockers identified in the simulated review are closed, but
the candidate is not yet an immutable public release and several author-owned
facts still require final confirmation. Submitting the local tree as-is would
therefore risk an editorial return or a major-revision decision, not direct
acceptance.

**Expected state after the external gates below are closed: Minor Revision is
the most defensible expectation.** The remaining scientific limitation is not a
software defect: the 150-episode reference audit is observational, several
cells are sparse or structurally unavailable, and only the
aggregate-analysis-to-artifact stage is publicly rerunnable. The manuscript
states these limits and does not claim ranking or causality. “Accept-ready” and
direct acceptance are not claimed.

## Closed internal issues

### 1. Claims were not traceable end to end

- Fix: froze a text-free, self-hashed 150-episode aggregate analysis and its
  registered configuration; generated ten tables, four accessible SVGs, four
  figure sidecars, publication data, and a self-hashed manifest.
- Files: `paper/data/analysis-deterministic-q14-v1.json`,
  `paper/config/qualification-analysis-config-v0.1.json`, and
  `paper/results/deterministic-q14-v1/`.
- Verification: `qualification-verify-public-analysis`,
  `qualification-verify-publication`, and `qualification-reproduce-check`.
  The reference bundle contains 20 files and regenerates byte for byte.

### 2. Manuscript numbers could drift from generated results

- Fix: introduced seven claim groups with unique CSV selectors, expected
  values, and matching LaTeX claim markers.
- Files: `paper/claim-ledger.json` and `paper/verify_claims.py`.
- Verification: the verifier rejects missing/duplicate source rows, mismatched
  values, analysis-identity drift, or missing manuscript markers.

### 3. Public release could expose private text or linkage

- Fix: added an aggregate release-boundary validator that rejects raw
  question/prompt/answer/response/rationale fields, API-key and credential
  variants, request identifiers, secret-shaped strings, and Windows, UNC, or
  common POSIX local absolute paths. Prompt/response token counts remain valid
  aggregate cost fields.
- Files: `src/mathaudit/qualification_publication.py` and
  `tests/test_qualification_composite.py`.
- Verification: positive validation of the frozen public analysis plus negative
  tests for raw answer, provider request identifier, and local-path injection.

### 4. Reproduction boundary was overstated

- Fix: documented and enforced the supported boundary as
  **aggregate analysis to tables/figures/manuscript values**. Raw benchmark
  text, provider calls, answers, credentials, request linkage, trajectories,
  and annotator rationales are excluded. No “full open-data reproduction” claim
  remains.
- Files: `paper/README.md`, `README.md`, `paper/softwarex.tex`, and
  `docs/research_governance.md`.
- Verification: boundary command output and the absence scan are part of the
  release checks.

### 5. Statistical definitions and manuscript language diverged

- Fix: aligned fixed-source integer contingency phi with the episode-balanced
  source-type estimator; documented complete-case versus registered-episode
  denominators, undefined marginals, clustered bootstrap, precision flags,
  repair/harm opportunities, direct adoption versus text proxy, joint failure,
  provenance facets, and model-based effective support.
- Files: `docs/statistical_contract.md`, `src/mathaudit/metrics.py`,
  `src/mathaudit/qualification_analysis.py`, and `paper/softwarex.tex`.
- Verification: metric oracle/unit tests, the frozen configuration, generated
  CSV schemas, and the numerical claim ledger.

### 6. Observational results invited causal or ranking interpretation

- Fix: disabled system ranking in analysis and artifact manifests; described
  repair/harm and utilization as observational; separated selective invocation
  and scoreability; retained null, undefined, structurally absent, and
  imprecise cells.
- Files: `paper/softwarex.tex`, `docs/statistical_contract.md`, and
  `paper/experiment-validation.md`.
- Verification: the experiment-agent validation checks all 11 specified
  fallacies and records cautions for complete-case selection, collider/Berkson
  effects, survivorship, and forking paths.

### 7. Unknown agent systems had no explicit integration boundary

- Fix: defined three routes: direct canonical export, conservative
  OpenTelemetry mapping, or a small versioned adapter. Fidelity levels control
  which analyses are permitted; missing evidence is never fabricated.
- Files: adapter modules under `src/mathaudit/adapters/`, canonical schemas,
  `docs/adding_an_adapter.md`, `docs/compatibility.md`, and the Software
  description section of `paper/softwarex.tex`.
- Verification: built-in adapter fixtures, coverage reports, semantic graph
  validation, and adapter tests.

### 8. Ingest could silently succeed on an empty directory glob

- Fix: directory input with zero matches now fails with a visible diagnostic
  and nonzero CLI exit status.
- Files: `src/mathaudit/ingest.py`, `src/mathaudit/cli.py`, and
  `tests/test_cli.py`.
- Verification: CLI regression test for an empty glob.

### 9. Package/schema version language was inconsistent

- Fix: standardized on package candidate 0.2.0 and canonical episode Schema
  1.0; historical Schema 0.1 remains explicitly migratable. Qualification
  format identifiers remain immutable provenance.
- Files: `pyproject.toml`, `src/mathaudit/__init__.py`, `CHANGELOG.md`,
  `docs/compatibility.md`, `docs/migrating_to_v1.md`, and manuscript metadata.
- Verification: lock consistency, schema inventory, migration tests, package
  metadata inspection, and clean-wheel smoke tests.

### 10. Tests, packaging, and CI did not cover the paper release

- Fix: CI now covers Ubuntu and Windows on Python 3.10 and 3.12, lint/format,
  tests, paper boundary/reproduction/claim/source-manifest checks, dependency
  audit, distribution build, and a clean-wheel CLI smoke test. Paper PNGs,
  source, references, public data, and manifests are included in source builds.
- Files: `.github/workflows/ci.yml`, `MANIFEST.in`, `pyproject.toml`, and
  `paper/build_submission_manifest.py`.
- Verification: local test, lint, lock, dependency, build, archive-content, and
  clean-install checks. A remote CI run on the final immutable commit remains an
  external release gate.

### 11. Novelty and citations were vulnerable to overclaiming

- Fix: replaced priority language with a capability-level comparison against
  MathGoal, A2E, MASEval, TRACER, LEDGER, AgentTrace, and OpenTelemetry. A blank
  capability is not interpreted as impossible extension.
- Files: `docs/related_work_matrix.md`, `paper/citation-audit.md`,
  `paper/references_final.bib`, and `paper/softwarex.tex`.
- Verification: each cited record is linked to its primary publication,
  preprint, or official specification; the compiled bibliography has no
  undefined citations.

### 12. Human-origin records created an integrity/governance risk

- Fix: excluded all private human ratings, calibration, identity linkage, and
  independent-reuse observations from the manuscript evidence base and public
  bundle. Structural validators are not represented as ethics or origin proof.
- Files: `docs/research_governance.md`, `paper/README.md`, and the Ethics and
  Validation statements in `paper/softwarex.tex`.
- Verification: no human-derived label, agreement statistic, quote, or reuse
  result appears in the claim ledger or reference-audit findings.

### 13. Manuscript structure and diagrams were not release-bound

- Fix: migrated the article to the author-supplied SoftwareX OSP LaTeX
  structure, completed C1--C8 metadata, kept the five prescribed sections, and
  revised both diagrams to show data boundaries, fidelity gates, audit-only
  reference-answer flow, non-causal results, and the provider-free reproduction
  route.
- Files: `paper/softwarex.tex`, `paper/references_final.bib`, and
  `paper/figures/`.
- Verification: Tectonic compilation, PDF rendering, page-by-page visual
  inspection, and checks for undefined references/citations.

## Verification snapshot

- Public test suite: 147 tests passed locally. Eighteen additional local
  development tests depend on the intentionally excluded private `research/`
  tree and are not counted as release evidence.
- Static checks: Ruff lint and format checks passed.
- Lock: `uv lock --check` passed.
- Public audit: 150 episodes, six panels, registered configuration hash
  verified; release-boundary check passed.
- Artifact reproduction: all 20 files byte-identical.
- Claim lineage: seven claim groups passed.
- Dependency audit: no known vulnerabilities reported for resolved third-party
  packages; the unpublished local package is necessarily not found on PyPI.
- Build/install: source distribution and platform-independent wheel built; the
  wheel installed and ran the CLI/schema/provider-free demo in a clean Python
  3.12 environment.
- PDF: compiled and visually inspected; no undefined citations or references.
- Template limits: approximately 2,588 main-text words including float text,
  96 abstract words, two figures, and all five mandatory OSP sections.

These are local candidate results. They do not assert that the final public
commit has passed remote GitHub Actions until that run exists.

## External blockers (must be closed by people or external services)

1. Both authors must approve the exact final manuscript, authorship order,
   CRediT roles, funding wording, AI disclosure, conflict declaration, data
   statement, and submission files.
2. The corresponding author must confirm that `wqyan@tju.edu.cn` is the intended
   submission/support address together with the stated Yantai University
   affiliation.
3. The authors must confirm that “research project led by Weiqing Yan; no
   external funding agency or grant number declared” is the complete and
   accurate funding statement.
4. The accepted source tree must be committed, tagged `v0.2.0`, and published as
   a GitHub Release; C2 should then be changed to the immutable tag or commit
   URL, and remote CI must pass on that exact commit.
5. If an archival DOI is requested or desired, a real Zenodo or equivalent
   deposit must be created and checked after release. No DOI is asserted now.
6. The corresponding author must complete the journal submission forms and any
   institutional or publisher declarations. Software cannot supply those
   attestations.

## Residual scientific and editorial risks

- Twenty-five episodes per system/stratum leave rare complete-case and
  transition cells imprecise; the hard ICMA all-wrong interval is especially
  wide.
- Different observability and scoreability across systems prevent fair ranking.
- Selective tool invocation prevents causal repair/harm or tool-value claims.
- Exact string repetition is narrower than semantic redundancy.
- The public aggregate supports strong computational reproducibility at its
  stated boundary, but a reviewer may still request controlled raw-data access
  or a redistribution/legal explanation for the private benchmark trajectories.
- Excluding the independent-person reuse record removes a potentially useful
  usability claim. The provider-free clean-install path partly mitigates this,
  but it is not independent user evidence.
- Recent adjacent agent-auditing work is fast-moving; the citation and
  capability matrix should be rechecked immediately before submission.

## Reassessment

The candidate is no longer a likely reject for software incompleteness,
unsupported headline claims, unverifiable manuscript numbers, or unresolved
human-derived evidence. It is a technically strong **Major Revision** candidate
until the immutable release and author-owned gates exist. Once those gates are
closed without changing the evidence base, **Minor Revision** is the realistic
pre-submission expectation. The work should not be labelled Accept-ready until
the actual release commit, remote CI, metadata, and author approvals are all
verified.
