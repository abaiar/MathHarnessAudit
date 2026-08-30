# Compatibility and deprecation policy

MathHarnessAudit is currently preparing its v1.0 release. The canonical episode
contract is frozen as Schema v1.0, while historical v0.1 episodes remain readable
through an explicit lossless migration. Qualification formats keep their
original version identifiers because they are immutable run provenance rather
than aliases for a new contract.

## Public contracts

The supported public surface consists of:

- the `mathaudit` CLI commands documented by `--help`;
- Pydantic objects in `mathaudit.models`;
- the `Adapter`, `ProblemContext` and `RunContext` protocol;
- JSON/JSONL formats with explicit `format` or `schema_version` fields;
- JSON Schemas embedded in the installed `mathaudit` package and exportable with
  `mathaudit export-schemas --output-dir <empty-directory>`;
- report/publication manifests and their declared artifact hashes.

Functions beginning with `_`, undocumented module constants, HTML/CSS structure
and internal intermediate dictionaries are not compatibility promises.

## Version rules

- Package releases follow semantic versioning after 1.0.
- Every adapter has an independent version recorded in each episode.
- A Schema changes incompatibly only under a new schema/format version; an old
  file is never silently reinterpreted under new semantics.
- Parser corrections that change canonical episodes bump the adapter version and
  require full re-ingestion of affected traces.
- Scorer corrections bump the scorer version and require complete rescoring of
  affected targets while retaining the earlier labels.
- Metric-definition changes require a result-manifest version bump and regenerated
  reports; a report hash from the older definition remains historical evidence.

## Deprecation after v1.0

A public CLI option or Python symbol will normally be announced for at least one
minor release before removal. A deprecated reader remains available long enough
to export the prior format to canonical JSON. Security, privacy or scientifically
invalid behavior may be disabled immediately and will be documented as such.

The v1.0 candidate includes an explicit canonical episode migration and tests
that cover every public v0.1 fixture. The machine-readable strategy record is
`schemas/mathaudit-v1-compatibility.json`; migration instructions are in
`docs/migrating_to_v1.md`. Final compatibility claims still require repeating
these tests on the immutable release commit.
