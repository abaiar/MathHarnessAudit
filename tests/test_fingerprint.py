# SPDX-License-Identifier: MIT

import json

import pytest

from mathaudit.fingerprint import (
    ALGORITHM,
    fingerprint_source_tree,
    verify_source_fingerprint,
    write_source_fingerprint,
)


def test_source_fingerprint_is_explicit_locale_free_and_verifiable(tmp_path):
    root = tmp_path / "source"
    (root / "中文").mkdir(parents=True)
    (root / "z.txt").write_text("z", encoding="utf-8")
    (root / "A.txt").write_text("a", encoding="utf-8")
    (root / "中文" / "证据.txt").write_text("proof", encoding="utf-8")
    (root / ".venv").mkdir()
    (root / ".venv" / "private.txt").write_text("ignored", encoding="utf-8")

    manifest = fingerprint_source_tree(root, system_id="fixture")
    assert manifest["algorithm"] == ALGORITHM
    assert manifest["file_count"] == 3
    assert [item["path"] for item in manifest["files"]] == [
        "A.txt",
        "z.txt",
        "中文/证据.txt",
    ]
    assert (
        verify_source_fingerprint(root, manifest)["manifest_sha256"] == manifest["manifest_sha256"]
    )


def test_source_fingerprint_detects_tampering_and_extra_files(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    (root / "one.py").write_text("one", encoding="utf-8")
    manifest = fingerprint_source_tree(root, system_id="fixture")
    (root / "one.py").write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="drift"):
        verify_source_fingerprint(root, manifest)

    (root / "one.py").write_text("one", encoding="utf-8")
    (root / "extra.py").write_text("extra", encoding="utf-8")
    with pytest.raises(ValueError, match="drift"):
        verify_source_fingerprint(root, manifest)


def test_source_fingerprint_exclusions_and_self_hash(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    (root / "keep.py").write_text("keep", encoding="utf-8")
    (root / "runtime.lock").write_text("generated", encoding="utf-8")
    manifest = fingerprint_source_tree(root, system_id="fixture", excluded_paths=["runtime.lock"])
    assert manifest["file_count"] == 1
    altered = json.loads(json.dumps(manifest))
    altered["system_id"] = "changed"
    with pytest.raises(ValueError, match="self-hash"):
        verify_source_fingerprint(root, altered)


def test_source_fingerprint_writer_refuses_overwrite(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    (root / "one.py").write_text("one", encoding="utf-8")
    manifest = fingerprint_source_tree(root, system_id="fixture")
    output = tmp_path / "manifest.json"
    write_source_fingerprint(output, manifest)
    assert json.loads(output.read_text())["self_sha256"] == manifest["self_sha256"]
    with pytest.raises(FileExistsError):
        write_source_fingerprint(output, manifest)
