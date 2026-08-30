# Migrating canonical episodes to v1.0

MathHarnessAudit v1.0 freezes the canonical episode field meanings exercised by
the Paper 1 reference audit. Historical v0.1 episode files remain readable. They
are never silently relabelled: migration is an explicit, lossless operation.

```powershell
mathaudit migrate-episode-v1 legacy-episodes.jsonl `
  --output stable-episodes.jsonl
```

The command validates the old record through the Pydantic and semantic graph
checks, changes only `schema_version` from `0.1` to `1.0`, validates the result,
and refuses to overwrite an existing destination. Running it on an already-v1.0
file is idempotent apart from normal canonical JSON serialization.

Use `schemas/mathaudit-episode-v1.0.schema.json` for new integrations. The old
`mathaudit-episode-v0.1.schema.json` remains shipped so archived research records
can be checked against the contract under which they were created.

Qualification authorizations, sample/run manifests, and publication
configurations keep their historical format identifiers. Renaming those files
would sever their frozen provenance without changing their semantics. Their
unchanged compatibility policy and fixture coverage are machine-recorded in
`schemas/mathaudit-v1-compatibility.json`.

Adapter authors should emit v1.0 episodes for new conversions. The canonical
pass-through adapter accepts both versions; downstream validation, scoring,
metrics, reports, and Parquet export operate on either version.
