# SPDX-License-Identifier: MIT

"""Access to JSON Schemas embedded in installed MathHarnessAudit packages."""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path
from typing import Any


def _schema_root() -> Any:
    return files("mathaudit").joinpath("schemas")


def schema_names() -> tuple[str, ...]:
    """Return the stable, sorted names of embedded JSON Schemas."""

    return tuple(
        sorted(
            item.name
            for item in _schema_root().iterdir()
            if item.is_file() and item.name.endswith(".json")
        )
    )


def read_schema_text(name: str) -> str:
    """Read one embedded Schema after rejecting traversal or unknown names."""

    if name not in schema_names():
        raise ValueError(f"unknown MathHarnessAudit schema: {name}")
    return _schema_root().joinpath(name).read_text(encoding="utf-8")


def export_schemas(output_dir: Path) -> list[Path]:
    """Export all embedded Schemas without merging into a nonempty directory."""

    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"schema output directory must be empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name in schema_names():
        destination = output_dir / name
        destination.write_text(read_schema_text(name), encoding="utf-8")
        written.append(destination)
    return written
