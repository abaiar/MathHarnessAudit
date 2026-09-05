# SPDX-License-Identifier: MIT

"""Write or verify the public source inputs for the SoftwareX submission."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "paper" / "submission-source-manifest.json"
ROOT_FILES = (
    ".gitignore",
    ".github/workflows/ci.yml",
    "CHANGELOG.md",
    "CITATION.cff",
    "LICENSE",
    "Licence.txt",
    "MANIFEST.in",
    "README.md",
    "pyproject.toml",
    "uv.lock",
)
ROOT_DIRS = ("docs", "examples", "schemas", "src", "tests", "paper")
EXCLUDED_PARTS = {"__pycache__", "build", "submission"}
EXCLUDED_NAMES = {
    MANIFEST.name,
    "MathHarnessAudit_SoftwareX_v0.2.0.pdf",
    "MathHarnessAudit_SoftwareX_v0.2.1.pdf",
    "softwarex.aux",
    "softwarex.bbl",
    "softwarex.blg",
    "softwarex.log",
    "softwarex.out",
    "softwarex.pdf",
    "softwarex.spl",
}
EXCLUDED_RELATIVE_PATHS = {
    "paper/figures/fig1_architecture_v2.html",
    "paper/figures/fig2_workflow_v2.html",
    "tests/test_budget_gateway.py",
    "tests/test_phase6_calibration_coordination.py",
    "tests/test_qualification_runners.py",
}
TEXT_SUFFIXES = {
    ".bib",
    ".c",
    ".cff",
    ".cfg",
    ".csv",
    ".ini",
    ".json",
    ".jsonl",
    ".md",
    ".py",
    ".ps1",
    ".rst",
    ".sh",
    ".tex",
    ".toml",
    ".tsv",
    ".txt",
    ".yml",
    ".yaml",
    ".svg",
}


def sha256(path: Path) -> str:
    """Hash canonical text bytes and raw bytes for binary artifacts."""
    if path.suffix.lower() in TEXT_SUFFIXES:
        data = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        return hashlib.sha256(data).hexdigest()
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_size(path: Path) -> int:
    """Return the byte size under the same text-normalization rule."""
    if path.suffix.lower() in TEXT_SUFFIXES:
        return len(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n"))
    return path.stat().st_size


def source_paths() -> list[Path]:
    paths = [ROOT / name for name in ROOT_FILES]
    for directory in ROOT_DIRS:
        paths.extend(path for path in (ROOT / directory).rglob("*") if path.is_file())
    selected = []
    for path in paths:
        relative = path.relative_to(ROOT)
        if (
            path.name in EXCLUDED_NAMES
            or relative.as_posix() in EXCLUDED_RELATIVE_PATHS
            or any(part in EXCLUDED_PARTS for part in relative.parts)
            or any(part.endswith(".egg-info") for part in relative.parts)
        ):
            continue
        selected.append(path)
    missing = [path for path in selected if not path.exists()]
    if missing:
        raise FileNotFoundError("missing submission source: %s" % missing[0])
    return sorted(set(selected), key=lambda path: path.as_posix())


def payload() -> dict[str, Any]:
    files = [
        {
            "path": path.relative_to(ROOT).as_posix(),
            "bytes": canonical_size(path),
            "sha256": sha256(path),
        }
        for path in source_paths()
    ]
    result: dict[str, Any] = {
        "format": "mathaudit-softwarex-submission-source-manifest-v1",
        "candidate_version": "0.2.1",
        "release_status": "immutable GitHub tag/release v0.2.1; archival DOI not asserted",
        "scope": "Public software, tests, documentation, and aggregate paper reproduction inputs; text hashes normalize CRLF to LF",
        "file_count": len(files),
        "files": files,
    }
    encoded = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    result["self_sha256"] = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="freeze the current source manifest")
    args = parser.parse_args()
    current = payload()
    if args.write:
        MANIFEST.write_text(
            json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(json.dumps({"status": "written", "path": str(MANIFEST), **current}))
        return 0
    if not MANIFEST.exists():
        raise FileNotFoundError("submission source manifest has not been written")
    expected = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if expected != current:
        expected_files = {row["path"]: row for row in expected.get("files", [])}
        current_files = {row["path"]: row for row in current["files"]}
        changed = sorted(
            path
            for path in expected_files.keys() | current_files.keys()
            if expected_files.get(path) != current_files.get(path)
        )
        raise ValueError("submission source drift: %s" % ", ".join(changed[:20]))
    print(
        json.dumps(
            {
                "status": "passed",
                "file_count": current["file_count"],
                "self_sha256": current["self_sha256"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
