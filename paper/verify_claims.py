# SPDX-License-Identifier: MIT

"""Verify registered manuscript claims against the generated CSV artifacts."""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LEDGER_PATH = ROOT / "paper" / "claim-ledger.json"
RESULTS = ROOT / "paper" / "results" / "deterministic-q14-v1"


def _matches(row: dict[str, str], where: dict[str, str]) -> bool:
    return all(row.get(key) == value for key, value in where.items())


def _assert_value(observed: str, expected: Any, label: str) -> None:
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        if observed == "":
            raise AssertionError(f"{label}: missing numeric value")
        actual = float(observed)
        if not math.isclose(actual, float(expected), rel_tol=1e-12, abs_tol=1e-12):
            raise AssertionError(f"{label}: expected {expected!r}, observed {observed!r}")
    elif observed != expected:
        raise AssertionError(f"{label}: expected {expected!r}, observed {observed!r}")


def _check_expected_rows(
    claim_id: str, rows: list[dict[str, str]], expected_rows: list[dict[str, Any]]
) -> None:
    for expected in expected_rows:
        panel_id = str(expected["panel_id"])
        matches = [row for row in rows if row.get("panel_id") == panel_id]
        if len(matches) != 1:
            raise AssertionError(f"{claim_id}: expected one row for {panel_id}")
        for field, value in expected.items():
            _assert_value(matches[0].get(field, ""), value, f"{claim_id}.{field}")


def main() -> int:
    ledger = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    manuscript_path = ROOT / ledger["manuscript"]
    manuscript = manuscript_path.read_text(encoding="utf-8")
    checked = []
    for claim in ledger["claims"]:
        claim_id = claim["claim_id"]
        marker = f"% claim-id:{claim_id}"
        if marker not in manuscript:
            raise AssertionError(f"{claim_id}: manuscript marker missing")
        source = RESULTS / claim["source"]
        with source.open(encoding="utf-8", newline="") as handle:
            rows = [row for row in csv.DictReader(handle) if _matches(row, claim.get("where", {}))]
        if "expected" in claim:
            if len(rows) != 1:
                raise AssertionError(f"{claim_id}: selector returned {len(rows)} rows")
            for field, value in claim["expected"].items():
                _assert_value(rows[0].get(field, ""), value, f"{claim_id}.{field}")
        else:
            _check_expected_rows(claim_id, rows, claim["expected_rows"])
        checked.append({"claim_id": claim_id, "source": claim["source"]})
    print(
        json.dumps(
            {
                "status": "passed",
                "claim_count": len(checked),
                "analysis_sha256": ledger["analysis_sha256"],
                "manuscript": ledger["manuscript"],
                "claims": checked,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
