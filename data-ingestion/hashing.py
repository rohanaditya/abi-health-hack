"""Stable row hashing for change detection."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def row_hash(payload: dict[str, Any]) -> str:
    """Return sha256 hex digest of a dict serialized with sorted keys."""
    serialized = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
