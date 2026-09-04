# Paper reproduction bundle

This directory is the public, provider-free reproduction surface for the
SoftwareX submission candidate.

## What can be reproduced

`data/analysis-deterministic-q14-v1.json` is the frozen, self-hashed aggregate
analysis for 150 complete episodes in six registered system-by-stratum panels.
It contains panel-level source inventories, explicit denominators, contingency
cells, intervals, cost summaries, transition counts, utilization summaries,
repetition counts, and final-outcome summaries. It contains no benchmark text,
prompt, response, reference answer, human rationale, credential, provider
request identifier, or local absolute path.

From a clean checkout, run:

```powershell
python -m pip install -e ".[schema]"
mathaudit qualification-verify-public-analysis `
  --analysis paper/data/analysis-deterministic-q14-v1.json `
  --config paper/config/qualification-analysis-config-v0.1.json
mathaudit qualification-verify-publication `
  --bundle-dir paper/results/deterministic-q14-v1 `
  --analysis paper/data/analysis-deterministic-q14-v1.json
mathaudit qualification-reproduce-check `
  --analysis paper/data/analysis-deterministic-q14-v1.json `
  --reference-dir paper/results/deterministic-q14-v1
python paper/verify_claims.py
python paper/build_submission_manifest.py
```

The second command verifies every registered artifact and its self-hashed
manifest. The third regenerates the full publication bundle in a temporary
directory and requires byte identity with the committed reference. The fourth
checks each registered numerical manuscript claim against exactly one CSV row
and verifies that the corresponding claim marker exists in the LaTeX source.
The final command rejects drift from the frozen public submission sources.

## What cannot be reproduced from this public bundle

The public files do not repeat provider calls, expose restricted benchmark
rows, reconstruct private model traces, or rescore raw answers. Therefore the
supported reproduction claim is **aggregate-analysis-to-artifact**: tables,
figures, sidecars, and manuscript values are reproducible from the released
analysis snapshot. Raw-run and scoring provenance is represented by hashes and
retained privately for audit, not by publicly redistributable content.

The human-rating and independent-person reuse records are not part of this
paper evidence bundle. Their provenance and applicable institutional-governance
status are unresolved external matters; excluding them prevents a private or
ambiguous record from being promoted into a scientific claim.

## Directory map

- `config/`: exact preregistered analysis configuration; its raw SHA-256 is
  bound by the analysis snapshot.
- `data/`: text-free aggregate analysis input.
- `results/`: generated CSV/SVG outputs and self-hashed manifests.
- `claim-ledger.json`: expected values and row selectors for manuscript claims.
- `verify_claims.py`: standard-library verifier for the claim ledger.
- `experiment-validation.md`: ARS experiment-agent validation, assumptions,
  11-fallacy scan, and the exact reproducibility boundary.
- `softwarex.tex` and `references_final.bib`: SoftwareX OSP manuscript source.
- `figures/`: deterministic architecture/workflow figures used by the paper.
