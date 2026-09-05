# Statistical contract

This document fixes the estimands, denominators, missingness rules, and
interpretive limits used by MathHarnessAudit v0.2.2. The frozen reference audit
continues to use its preregistered v0.1 analysis configuration; v0.2.2 changes
documentation and verification, not the observed outcomes or selection rules.

## Availability before correctness

Every source is evaluated against the registered episode population in this
order: eligible, called, produced, binary-scorable, correct. `not_called`,
`no_vote`, `failed`, `timeout`, `abstain`, `unscorable`, and `not_observable`
are distinct states. None is silently converted to an incorrect answer.

- opportunity rate = eligible episodes / registered episodes;
- call rate = called episodes / eligible episodes;
- production rate = produced episodes / called episodes;
- scorable rate = binary-scorable latest source outputs / produced episodes;
- conditional correctness = correct / (correct + incorrect);
- operational support rate = correct / registered episodes.

Zero denominators yield `null`, not zero. Binomial proportions use two-sided
95% Clopper--Pearson intervals.

## Fixed-source dependence

For two named sources, only episodes where both latest outputs have binary
labels enter the complete-case table. With the order `(both correct, A correct/B
wrong, A wrong/B correct, both wrong)`, phi is

```
(n00*n11 - n01*n10) /
sqrt((n00+n01)(n10+n11)(n00+n10)(n01+n11))
```

Phi is `null` when either marginal has zero variance. Its bootstrap resamples
complete-case episodes and therefore does not impute missing sources. Every
bootstrap output reports the requested, defined, and undefined replicate counts
and the defined fraction. When any resampled table has a zero-variance marginal,
the reported 2.5--97.5% percentile range is conditional on the subset of
resamples where phi is defined. It is not described as an unconditional 95%
confidence interval or as having established nominal coverage. If no resample
has defined phi, the range remains `null`.

## Source-type dependence

An episode may contain many sources of one type. Pooling every candidate pair
would give more weight to episodes with more agents, so the primary estimator
is episode-balanced:

1. form all eligible source pairs inside each episode;
2. tabulate that episode's four pair cells;
3. divide each cell by the episode's number of eligible pairs;
4. average the four proportions over episodes that contain at least one pair;
5. compute phi from the four averaged proportions;
6. resample episodes and repeat steps 4--5;
7. report the 2.5--97.5% percentile range among defined phi resamples together
   with the requested, defined, and undefined replicate counts.

Thus the primary four cells are proportions, not integer counts. Integer pooled
pair cells and pair-weighted phi are emitted only as sensitivity summaries.
`episodes_with_pairs` is the primary precision denominator. The historical
configuration field is named `minimum_complete_cases`; for source-type rows it
means the preregistered minimum number of informative episodes. The reference
audit threshold is 20. This naming clarification does not change the frozen
calculation.

The calculation is repeated for all, same-provenance, and different-provenance
pairs. A provenance label records declared derivational grouping; it does not
prove statistical independence.

## Joint failure

Two intentionally different estimands are reported:

- complete-case all-wrong: all registered sources have binary labels and all
  are wrong; denominator = complete cases;
- operational no-correct-support: none of the registered sources has a correct
  label; denominator = all registered episodes.

The operational estimand includes episodes with missing or unscorable sources
but does not call those sources wrong. Its meaning is “no observed correct
support,” not “every source failed.”

## Repair, harm, and use

For a registered upstream/checker direction:

- repair opportunity requires upstream wrong and checker correct;
- repair realization requires a repair opportunity and correct final output;
- harm opportunity requires upstream correct and checker wrong;
- harm realization requires a harm opportunity and incorrect final output.

Opportunity and realization denominators are emitted separately. These are
observational transitions: selective tool invocation, routing, and hidden
confounding prohibit causal language.

Direct adoption requires an observed decision whose candidates include both
sources and whose selected evidence includes the checker. Final text equality
is emitted separately as a proxy and is never renamed “tool use.”

## Repetition and effective support

Content-hash identity, normalized full-text identity, and normalized-answer
identity have separate denominators. Exact identity is not semantic
equivalence and not correctness.

The optional variance-equivalent support curve
`k / (1 + (k - 1) * rho)` assumes exchangeable sources with common pairwise
correlation. It is a model summary, not a literal number of independent votes.

## Precision, multiplicity, and scope

The reference audit is descriptive and reports all registered cells, including
null and imprecise ones. It does not perform cross-panel pooling, system ranking,
hypothesis testing, multiplicity-adjusted discovery, or architecture-causal
inference. Defined-resample bootstrap percentile ranges describe the observed
resampling distribution only after exposing undefined replicates. They do not
establish nominal coverage or repair selection bias, zero-variance instability,
or missingness.
