# SPDX-License-Identifier: MIT

"""Stable hashing helpers used by adapters and manifests."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def sha256_text(value: str) -> str:
    """Return the lowercase SHA-256 digest of canonical UTF-8 text."""

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def canonical_json(value: Any) -> str:
    """Serialize JSON-compatible data deterministically."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value: Any) -> str:
    """Return a digest for JSON-compatible data after canonical serialization."""

    return sha256_text(canonical_json(value))
