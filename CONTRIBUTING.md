# Contributing

MathHarnessAudit welcomes focused fixes, adapters, safe fixtures and
documentation improvements. Before opening a change:

1. do not include credentials, private traces, chain-of-thought or
   license-restricted benchmark text;
2. add a regression test for every semantic change;
3. preserve missingness, provenance and append-only scoring history;
4. bump adapter/scorer/format versions when output semantics change;
5. begin every new public Python file with `# SPDX-License-Identifier: MIT`;
6. run `uv run --all-extras pytest` and `uv run --extra dev ruff check src tests`.

Non-Python files remain covered by the root `LICENSE` and package metadata. Do
not insert license comments into formats, such as JSON, that do not permit them.

Adapter contributions must follow `docs/writing_an_adapter.md` and declare source
license, trace version and fidelity. Research-result changes require a linked
deviation record and regeneration from frozen inputs; pull requests must not edit
paper numbers manually.

By participating, contributors agree to follow `CODE_OF_CONDUCT.md`. Final author
credit and CRediT roles are decided from documented contributions, not inferred
from commit count.
