# SPDX-License-Identifier: MIT

"""Build a deterministic SoftwareX source-and-PDF submission archive."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import build_submission_manifest

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.2.2"
MANIFEST = ROOT / "paper" / "submission-source-manifest.json"
PDF = ROOT / "paper" / f"MathHarnessAudit_SoftwareX_v{VERSION}.pdf"
OUTPUT = ROOT / "paper" / "submission" / f"MathHarnessAudit-SoftwareX-v{VERSION}.zip"
ARCHIVE_ROOT = f"MathHarnessAudit-SoftwareX-v{VERSION}"
FIXED_TIMESTAMP = (2026, 9, 5, 0, 0, 0)


def _write_entry(archive: zipfile.ZipFile, relative: str, data: bytes) -> None:
    info = zipfile.ZipInfo(f"{ARCHIVE_ROOT}/{relative}", FIXED_TIMESTAMP)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    archive.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def main() -> int:
    expected = json.loads(MANIFEST.read_text(encoding="utf-8"))
    current = build_submission_manifest.payload()
    if expected != current:
        raise ValueError("submission source manifest is stale; freeze it before archiving")
    if not PDF.is_file():
        raise FileNotFoundError(f"missing compiled manuscript: {PDF}")

    entries = [(row["path"], ROOT / row["path"]) for row in expected["files"]]
    entries.extend(
        [
            ("paper/submission-source-manifest.json", MANIFEST),
            (f"paper/{PDF.name}", PDF),
        ]
    )
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(OUTPUT, "w") as archive:
        for relative, source in sorted(entries):
            _write_entry(archive, relative, source.read_bytes())

    with zipfile.ZipFile(OUTPUT) as archive:
        corrupt = archive.testzip()
        if corrupt is not None:
            raise ValueError(f"corrupt archive member: {corrupt}")
        names = archive.namelist()
    print(
        json.dumps(
            {
                "status": "written",
                "path": str(OUTPUT),
                "entry_count": len(names),
                "source_manifest_sha256": expected["self_sha256"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
