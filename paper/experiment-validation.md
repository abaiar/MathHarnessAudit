# Material Passport

- Origin Skill: academic-research-suite / experiment-agent
- Origin Mode: validate
- Origin Date: 2026-09-04
- Verification Status: VERIFIED
- Version Label: qualification_audit_validation_v1
- Source: `paper/data/analysis-deterministic-q14-v1.json`
- Registered configuration: `paper/config/qualification-analysis-config-v0.1.json`
- Evidence boundary: frozen aggregate analysis to publication artifacts

# Validation report

Overall confidence is **CAUTION** for substantive cross-system inference and
**SOLID** for deterministic aggregate-to-artifact reproduction. The distinction
is deliberate: exact software reproduction does not make sparse observational
cells precise or causal.

## Statistical findings

| Finding | Estimand and observed value | Interval / denominator | Assessment |
|---|---|---|---|
| MathGoal-standard LLM--LLM dependence | Episode-balanced phi = -0.0061 | 22 informative episodes; 182 pairs; 6,439/10,000 bootstrap draws defined; conditional 2.5--97.5 percentile range [-0.0250, -0.0061] | Adequate only under the registered 20-episode precision flag; the range has no asserted nominal coverage and is not evidence of a universal zero correlation |
| MathGoal-standard LLM--Python dependence | Episode-balanced phi = 0.2592 | 16 informative episodes; 249 pairs; 6,465/10,000 draws defined; conditional range [0.1882, 0.3974] | Imprecise by the registered episode threshold; the 3,535 undefined draws remain reported |
| ICMA-standard LLM--Python dependence | Episode-balanced phi = 0.6794 | 14 informative episodes; 27 pairs; 6,486/10,000 draws defined; conditional range [0.4385, 1.0000] | Imprecise and compatible with a wide range of strong associations; the 3,514 undefined draws remain reported |
| MathRouter operational no-correct-support | 7/25 standard; 22/25 hard | Registered-episode denominator | Descriptive operational availability/outcome measure, not an all-sources-wrong probability |
| ICMA complete-case all-wrong | 0/13 standard; 1/4 hard | Exact 95% intervals [0, 0.2471] and [0.0063, 0.8059] | Hard-panel estimate is extremely uncertain |
| ICMA exact text repetition | 23/24 standard; 19/23 hard | Exact 95% intervals [0.7888, 0.9989] and [0.6122, 0.9505] | Clear exact-string redundancy; not semantic equivalence or correctness |

No null-hypothesis p-values or confirmatory discovery claims are registered.
Consequently, multiplicity correction is not retrofitted. All registered cells,
including null, structurally absent, and imprecise cells, remain in the public
tables.

## Assumptions and warnings

- Bootstrap resampling is clustered by episode and retains within-episode
  source dependence. Every output records requested, defined, and undefined
  replicate counts. Because the displayed percentile range conditions on draws
  where phi is defined, it is an instability diagnostic rather than an
  unconditional confidence interval with established 95% coverage. Resampling
  does not correct selective tool invocation.
- Source-type phi uses equal episode weight after within-episode normalization.
  Pooled pair counts are a sensitivity view only.
- The 20-episode rule is a preregistered reporting flag, not a guarantee of
  adequate statistical power. No retrospective power claim is made.
- Complete-case dependence and all-wrong estimates condition on binary
  scoreability. Operational no-correct-support uses every registered episode
  and answers a different question.
- The three systems and two difficulty strata are not exchangeable treatment
  groups. Cross-system ranking and architecture-effect inference are disabled.

## Eleven-fallacy scan

Coverage: **11/11 checked**.

| Fallacy | Status | Audit conclusion |
|---|---|---|
| Simpson's paradox | NOTE | No cross-panel pooled effect is reported. Panel rows remain separate, so no aggregate direction is used to override stratum-specific directions. |
| Ecological fallacy | NOTE | Episode-balanced source-type associations are not interpreted as properties of every individual agent or prompt. |
| Berkson's paradox | CAUTION | Conditioning on called and binary-scorable source pairs can induce selection associations. The paper limits inference to observable complete cases. |
| Collider bias | CAUTION | Tool invocation and scoreability may depend on upstream difficulty or trajectory state. No adjusted causal coefficient is claimed. |
| Base-rate neglect | PASS | Availability and registered-episode denominators precede conditional correctness and complete-case statistics. |
| Regression to the mean | N/A | There is no pre/post intervention or cohort selected by an extreme baseline score. |
| Survivorship bias | CAUTION | Complete-case rows alone would omit unavailable evidence. The separate all-episode operational estimand exposes this difference. |
| Look-elsewhere effect | PASS | The software exports all registered rows; the manuscript does not select claims by p-value or label exploratory cells significant. |
| Garden of forking paths | CAUTION | The analysis configuration and seed are frozen and public, but the audit remains descriptive; no confirmatory hypothesis-test interpretation is permitted. |
| Correlation implies causation | PASS | Repair/harm and dependence are explicitly described as observational transitions and associations. |
| Reverse causality | PASS | Directional stage labels do not support claims that a checker caused the final outcome; temporal ordering is not equated with causal identification. |

## Reproducibility verification

- Method: deterministic rerun from the public aggregate snapshot.
- Command: `mathaudit qualification-reproduce-check` with the committed
  analysis and reference bundle.
- Result: all 20 bundle files, including the manifest, matched byte for byte.
- Claim verification: seven numerical claim groups matched unique CSV selectors
  and LaTeX claim markers.
- Verdict at the stated boundary: **REPRODUCIBLE**.
- Raw provider-call and raw-answer-scoring rerun: **CANNOT VERIFY from the public
  bundle**, because benchmark text, prompts, responses, credentials, and request
  identifiers are intentionally excluded.

## Implication for future experiment design

A causal statement about tool value requires a new, prospectively registered
controlled fork: randomize tool availability or call/no-call assignment within
matched problems, hold model and decoding fixed, record intention-to-treat
outcomes, and size the experiment for repair and harm opportunities rather than
overall episode count. This is future work and is not presented as completed
evidence for the SoftwareX submission.
