"""Canonical JSON and content identities for DumbMoney research artifacts.

The wire convention is intentionally small and language neutral:

* UTF-8
* lexicographically sorted object keys
* compact separators
* no NaN or Infinity

Signatures belong to the DumbMoney authority plane.  This research package
only creates content identities and never signs capital or execution grants.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict


class CanonicalizationError(ValueError):
    """Raised when a value cannot be represented by the canonical wire form."""


def _normalize(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _normalize(value.model_dump(mode="json", exclude_none=False))
    if isinstance(value, Enum):
        return _normalize(value.value)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise CanonicalizationError("datetimes must be timezone-aware")
        utc = value.astimezone(timezone.utc)
        return utc.isoformat(timespec="microseconds").replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise CanonicalizationError("decimal values must be finite")
        normalized = value.normalize()
        if normalized == 0:
            return "0"
        return format(normalized, "f")
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CanonicalizationError("floating-point values must be finite")
        return 0.0 if value == 0 else value
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalizationError("object keys must be strings")
            result[key] = _normalize(item)
        return result
    if isinstance(value, (tuple, list)):
        return [_normalize(item) for item in value]
    if isinstance(value, (set, frozenset)):
        raise CanonicalizationError("sets have no canonical order")
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise CanonicalizationError(f"unsupported canonical value: {type(value).__name__}")


def canonical_json_bytes(value: Any) -> bytes:
    """Return the strict canonical JSON encoding for *value*."""

    try:
        encoded = json.dumps(
            _normalize(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise CanonicalizationError(str(exc)) from exc
    return encoded.encode("utf-8")


def canonical_json(value: Any) -> str:
    return canonical_json_bytes(value).decode("utf-8")


def content_hash(value: Any) -> str:
    return f"sha256:{hashlib.sha256(canonical_json_bytes(value)).hexdigest()}"


class CanonicalModel(BaseModel):
    """Frozen, extra-forbidding base for proof-carrying wire contracts."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    @property
    def content_hash(self) -> str:
        return content_hash(self)

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self)

    def canonical_json(self) -> str:
        return canonical_json(self)
