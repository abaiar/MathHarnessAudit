"""Cross-platform source-tree fingerprints for reference systems."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

from .hashing import sha256_json, sha256_text

FORMAT = "mathaudit-source-fingerprint-v0.1"
ALGORITHM = "sha256-lines-posix-path-utf8-byte-sort-v1"
DEFAULT_EXCLUDED_DIRECTORIES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
}


def _normalize_exclusions(values: Iterable[str]) -> List[str]:
    result = []
    for value in values:
        normalized = str(value).replace("\\", "/").strip("/")
        if not normalized or normalized in {".", ".."} or normalized.startswith("../"):
            raise ValueError("excluded paths must be nonempty root-relative paths")
        result.append(normalized)
    if len(result) != len(set(result)):
        raise ValueError("excluded paths must be unique")
    return sorted(result, key=lambda item: item.encode("utf-8"))


def _excluded(relative: str, excluded_paths: Sequence[str]) -> bool:
    return any(relative == item or relative.startswith(item + "/") for item in excluded_paths)


def fingerprint_source_tree(
    root: Path,
    *,
    system_id: str,
    excluded_paths: Sequence[str] = (),
    excluded_directories: Sequence[str] = tuple(sorted(DEFAULT_EXCLUDED_DIRECTORIES)),
) -> Dict[str, Any]:
    """Build a self-hashed, explicit file inventory with locale-free ordering."""

    source = root.resolve()
    if not source.is_dir():
        raise ValueError("source root is not a directory: %s" % root)
    if not system_id.strip():
        raise ValueError("system_id must not be empty")
    exclusions = _normalize_exclusions(excluded_paths)
    directory_exclusions = sorted(set(excluded_directories))
    files: List[Dict[str, Any]] = []
    for current, directories, filenames in os.walk(source, topdown=True, followlinks=False):
        current_path = Path(current)
        retained_directories = []
        for name in directories:
            candidate = current_path / name
            relative = candidate.relative_to(source).as_posix()
            if name in directory_exclusions or _excluded(relative, exclusions):
                continue
            if candidate.is_symlink():
                raise ValueError("source fingerprint refuses symbolic links: %s" % relative)
            retained_directories.append(name)
        directories[:] = retained_directories
        for name in filenames:
            path = current_path / name
            relative = path.relative_to(source).as_posix()
            if path.suffix.lower() == ".pyc" or _excluded(relative, exclusions):
                continue
            if path.is_symlink():
                raise ValueError("source fingerprint refuses symbolic links: %s" % relative)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            files.append({"path": relative, "sha256": digest, "bytes": path.stat().st_size})
    files.sort(key=lambda item: item["path"].encode("utf-8"))
    if not files:
        raise ValueError("source fingerprint contains no files")
    lines = ["%s  %s" % (item["sha256"], item["path"]) for item in files]
    payload = {
        "format": FORMAT,
        "system_id": system_id,
        "algorithm": ALGORITHM,
        "root_hint": source.name,
        "excluded_paths": exclusions,
        "excluded_directories": directory_exclusions,
        "file_count": len(files),
        "manifest_sha256": sha256_text("\n".join(lines)),
        "files": files,
    }
    payload["self_sha256"] = sha256_json(payload)
    return payload


def verify_source_fingerprint(root: Path, manifest: Dict[str, Any]) -> Dict[str, Any]:
    """Recompute an explicit fingerprint and reject file, policy, or hash drift."""

    if manifest.get("format") != FORMAT or manifest.get("algorithm") != ALGORITHM:
        raise ValueError("unsupported source fingerprint format or algorithm")
    claimed = manifest.get("self_sha256")
    hash_input = dict(manifest)
    hash_input.pop("self_sha256", None)
    if claimed != sha256_json(hash_input):
        raise ValueError("source fingerprint self-hash mismatch")
    recomputed = fingerprint_source_tree(
        root,
        system_id=str(manifest.get("system_id") or ""),
        excluded_paths=manifest.get("excluded_paths") or [],
        excluded_directories=manifest.get("excluded_directories") or [],
    )
    fields = ("file_count", "manifest_sha256", "files")
    mismatches = [field for field in fields if recomputed[field] != manifest.get(field)]
    if mismatches:
        raise ValueError("source fingerprint drift: %s" % ", ".join(mismatches))
    return {
        "system_id": recomputed["system_id"],
        "file_count": recomputed["file_count"],
        "manifest_sha256": recomputed["manifest_sha256"],
        "self_sha256": claimed,
    }


def write_source_fingerprint(path: Path, manifest: Dict[str, Any]) -> None:
    """Write a generated fingerprint only to an absent path."""

    if path.exists():
        raise FileExistsError("source fingerprint output already exists: %s" % path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
