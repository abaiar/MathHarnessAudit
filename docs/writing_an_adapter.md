# Writing a MathHarnessAudit adapter

An adapter is a semantics-preserving translator, not a parser that merely makes
JSON validate. Its job is to state what the source trace actually proves and to
mark everything else unobservable.

## 1. Identify the source contract first

Before code, freeze a real source snapshot and write down:

- one immutable run/episode identifier and problem join key;
- every possible source role and whether it is stable across runs;
- eligibility, invocation and outcome states for each role;
- candidate, tool, verifier and final-output fields;
- decisions that expose their inputs and selected outputs;
- derivation or visibility relationships;
- calls, tokens, latency and monetary units;
- fields that are absent from the trace and therefore cannot be inferred.

Do not infer `not_called` from a missing optional field unless the harness contract
proves the call opportunity existed. Use `not_observable` when the trace cannot
distinguish absence from lost instrumentation.

## 2. Implement the protocol

Create `src/mathaudit/adapters/<name>.py` with an adapter that implements
`mathaudit.adapters.base.Adapter`:

```python
class ExampleAdapter:
    name = "example"
    version = "0.1.0"

    def can_handle(self, payload):
        return payload.get("trace_format") == "example-v1"

    def convert(self, payload, problem, run):
        # Return one fully cross-referenced mathaudit.models.Episode.
        ...
```

`can_handle` must be conservative: one distinctive versioned signature is better
than several weak key guesses. `convert` must not mutate its input.

Construct stable IDs from source identifiers or canonical content hashes. Never
use list position alone when order can change. Source IDs describe stable roles;
run-local candidate IDs belong in metadata. If a tool result derives from a
candidate, keep the relationship in `provenance_edges` and normally keep both in
the same provenance group unless the tool establishes independent support.

## 3. Declare fidelity honestly

- **A — full:** evidence, decisions, provenance and final output are observable;
- **B — staged:** major stages are present but some fine-grained selection or
  provenance semantics are unavailable;
- **C — final-only:** only the final response is reliable.

Fidelity C is useful for survival/final-accuracy summaries but cannot support a
headline dependence, repair/harm or utilization audit. Adapter warnings must
name every important loss.

## 4. Register and test

Add the adapter instance to `BUILTIN_ADAPTERS` in
`src/mathaudit/adapters/__init__.py`. Then add a synthetic or explicitly
de-identified fixture and tests that prove:

- positive and negative `can_handle` cases;
- every ID is unique and every cross-reference resolves;
- produced evidence has a called/produced observation;
- uncalled, failed, timed-out and unobservable sources remain distinct;
- final output points to final-answer evidence;
- provenance is acyclic and duplicated text is not independent evidence;
- gold is absent from solver-visible trace/configuration fields;
- malformed, partial and error envelopes fail or receive the registered missing
  state instead of being silently accepted.

Run:

```powershell
uv run --all-extras pytest
uv run --extra dev ruff check src tests
uv run mathaudit ingest --help
uv run mathaudit validate canonical-output.jsonl
uv run mathaudit coverage canonical-output.jsonl
```

## 5. Supply evidence for review

An adapter contribution should include its source-format/version description,
license boundary, fidelity level, at least one safe fixture, expected coverage
report, tests, and a note explaining every inferred field. Do not attach private
traces, chain-of-thought, request credentials or benchmark text without explicit
redistribution permission.
