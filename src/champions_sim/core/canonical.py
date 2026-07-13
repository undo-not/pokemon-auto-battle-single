"""Canonical JSON and SHA-256 helpers for states, events, and replays."""

from __future__ import annotations

import hashlib
import json
from dataclasses import MISSING, fields, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping


def to_canonical_data(value: Any) -> Any:
    """Convert supported immutable domain values to JSON-compatible data.

    Floats and unordered containers are rejected intentionally: neither has a
    portable representation suitable for a replay/state identity contract.
    """

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        raise TypeError("floats are not supported in canonical domain data")
    if isinstance(value, Enum):
        return to_canonical_data(value.value)
    if is_dataclass(value) and not isinstance(value, type):
        converted: dict[str, Any] = {}
        for field in fields(value):
            item = getattr(value, field.name)
            if field.metadata.get("canonical_omit_default", False):
                if field.default is not MISSING and item == field.default:
                    continue
                if (
                    field.default_factory is not MISSING
                    and item == field.default_factory()
                ):
                    continue
            converted[field.name] = to_canonical_data(item)
        return converted
    if isinstance(value, Mapping):
        converted: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("canonical mappings require string keys")
            converted[key] = to_canonical_data(item)
        return converted
    if isinstance(value, (tuple, list)):
        return [to_canonical_data(item) for item in value]
    if isinstance(value, (set, frozenset)):
        raise TypeError("unordered containers are not canonical")
    if isinstance(value, Path):
        raise TypeError("filesystem paths are not canonical domain values")
    raise TypeError(f"unsupported canonical value: {type(value).__name__}")


def canonical_json(value: Any) -> str:
    """Return UTF-8-safe, whitespace-free JSON with sorted object keys."""

    return json.dumps(
        to_canonical_data(value),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def canonical_hash(value: Any) -> str:
    """Return the lowercase SHA-256 hex digest of canonical JSON."""

    payload = canonical_json(value).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
