# Troubleshooting

## `pyarrow` or `jsonschema` is missing

Parquet and general Schema validation are optional installations:

```powershell
pip install "math-harness-audit[parquet]"
pip install "math-harness-audit[schema]"
```

Use `pip install "math-harness-audit[parquet,schema]"` when both are needed.

## The scorer returns `unscorable`

This is a safety result, not automatically a bug. The deterministic scorer only
accepts registered exact, rational-numeric, restricted symbolic and categorical
forms. Proofs, ambiguous multi-part answers, sets/intervals outside the supported
path and prose-heavy conclusions should enter blinded adjudication. Do not widen
SymPy parsing or add an LLM judge merely to improve coverage.

## A metric has few or zero complete cases

Inspect `availability` first. Missing, failed, timed-out, not-called, abstaining
and unscorable observations are intentionally not converted to wrong answers.
Publication tables retain small cells with an imprecision flag. Change the
sample-size plan before outcomes are opened; never suppress an inconvenient cell.

## Dependence or repair/harm is unavailable at fidelity C

Final-only traces cannot reveal upstream evidence or selection decisions. Obtain
full/staged output, add instrumentation, or restrict the analysis to final
survival and accuracy. Do not manufacture evidence nodes from prose guesses.

## `source fingerprint drift`

Re-run `mathaudit verify-source-fingerprint` and inspect the explicit file list.
Do not update the expected hash until the change is understood, versioned and
approved as a new reference snapshot. Generated caches should be excluded by a
frozen policy, not deleted opportunistically to force a match.

## Qualification preflight is red

This is fail-closed behavior. Read each logical check in the report. A missing or
pending authorization, source/sample/lock drift, missing planned run manifest,
gold-separation failure or runner mismatch prohibits provider contact. Never edit
the report to green; fix the underlying artifact and regenerate it.

## An output directory “must be absent or empty”

Publication, adjudication, sampling and preparation commands refuse to overwrite
evidence. Choose a new versioned directory. Preserve the older directory and its
manifest until retention policy permits archival or deletion.

## A solver-visible gold leak is reported

Stop the run. Verify that `solver_visible/competition.jsonl` contains exactly
`idx,problem`, MathGoal input contains exactly `id,question`, and gold-bearing
records remain under `audit_only/`. Treat any contacted episode after a leak as a
protocol deviation.
