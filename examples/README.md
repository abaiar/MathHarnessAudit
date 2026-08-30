# Public fixture policy

All files in `examples/fixtures` are synthetic, author-generated records. They
imitate the structural fields needed by the adapters but contain no private model
trace, API identifier, benchmark-only prompt, or chain-of-thought.

- `icma/0.json` exercises staged reasoning, Python verification, validation,
  arbitration, and coordination.
- `mathrouter/1.json` exercises Hermes-style reasoning, executable evidence, and
  an observed final-selection event.
- `mathgoal_full.json` exercises full candidates, tool reports, verifier reports,
  and finalization.
- `otel.json` exercises GenAI span extraction and the explicit
  `mathaudit.final=true` bridge rule.
- `problems.jsonl` contains trivial arithmetic problems and gold answers used only
  by the audit side.
- `compute_authorization_pending.json` is structurally valid but deliberately
  cannot authorize compute until every owner-controlled cap/runtime field is
  completed and `status` becomes `authorized`.

Run `uv run --extra dev python examples/run_demo.py` from the repository root for
a provider-free end-to-end demonstration.
