# Functional positioning against adjacent software

This comparison is deliberately capability-level. A blank or “not a stated
focus” means the cited primary description does not make that capability a
central software contract; it is not a claim that no implementation could ever
be extended to provide it.

| Project | Primary object | Trace/provenance | Outcome-linked mathematical scoring | Availability-aware denominators | Error dependence / co-failure | Decision adoption and repair/harm | Reproducible paper-artifact manifest |
|---|---|---|---|---|---|---|---|
| MathHarnessAudit | Post-hoc evidence audit for mathematical-agent traces | Typed sources, observations, decisions, edges, fidelity | Conservative deterministic labels with explicit unscorable state | Yes | Named-source and episode-balanced type-pair estimators | Direct selection separated from text proxy; observational transitions | Yes, with byte-reproduction check |
| MathGoal | Construction and execution of mathematical solving workflows | Workflow/run artifacts | Yes, as part of solving and evaluation | Not its stated audit object | Not its stated focus | Route execution rather than post-hoc adoption audit | Public prediction/evaluation artifacts |
| A²E | End-to-end harness capability evaluation | Automatically instrumented standardized execution traces | General task evaluation | Execution metrics are central | Not described as the same evidence-error estimand | Planning, tool use, efficiency, recovery metrics | Different task/evaluation protocol |
| MASEval | Framework-agnostic multi-agent system comparison | System configurations and benchmark runs | General benchmark outcomes | Not its stated focus | Not its stated focus | System-level component comparisons | Evaluation framework rather than evidence ledger |
| TRACER | Claim-level generative provenance | Claim-to-tool-turn/evidence relations | Multimodal task evaluation, not the same math scorer | Not its stated focus | Not its stated focus | Provenance-derived constraints and credit | Different provenance/learning objective |
| LEDGER | Human review of agent execution graphs | Trace, evidence, workflow, and claim-support graphs | Not its stated focus | Not its stated focus | Not its stated focus | Exposes repair steps and validation coverage | Review/trace system rather than registered statistical audit |
| AgentTrace / OpenTelemetry GenAI | General observability and semantic telemetry | Structured logs/spans | No domain scorer | Records observability; no paper-specific denominator contract | No | No outcome-linked transition estimand | Telemetry standards, not publication analysis |

The verifiable difference is therefore not “MathHarnessAudit audits agents and
others do not.” Its narrower contribution is the tested integration of:

1. a fidelity-aware adapter boundary for heterogeneous math-agent traces;
2. source availability and missingness as explicit denominators;
3. conservative outcome labels linked to evidence nodes;
4. provenance-faceted dependence, co-failure, transitions, and direct adoption;
5. hash-bound, registered analysis-to-paper outputs.

This positioning does not support a “first” claim. It states a combination of
implemented interfaces and metrics that can be inspected in this repository.

Primary descriptions checked 2026-09-04:

- MathGoal: https://doi.org/10.1016/j.softx.2026.102887
- A²E: https://arxiv.org/abs/2608.07346
- MASEval: https://arxiv.org/abs/2603.08835
- TRACER: https://arxiv.org/abs/2605.09934
- LEDGER: https://arxiv.org/abs/2608.18398
- AgentTrace: https://arxiv.org/abs/2602.10133
- OpenTelemetry GenAI agent spans:
  https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-agent-spans.md
