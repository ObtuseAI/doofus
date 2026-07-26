"""Atomic JSON read/write with corruption recovery."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from doofus.core.doofus_events import utc_now
from doofus.core.doofus_paths import CANONICAL_RUNTIME


def _assert_runtime_write_allowed(path: Path) -> None:
    if os.environ.get("PYTEST_CURRENT_TEST") and os.environ.get("DOOFUS_ALLOW_LIVE_RUNTIME_TESTS", "0") != "1":
        try:
            if path.resolve().is_relative_to(CANONICAL_RUNTIME.resolve()):
                raise RuntimeError(f"pytest attempted to write live runtime path: {path}")
        except FileNotFoundError:
            if str(path).startswith(str(CANONICAL_RUNTIME)):
                raise RuntimeError(f"pytest attempted to write live runtime path: {path}")


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default if default is not None else {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        backup = path.with_suffix(path.suffix + ".corrupt")
        try:
            if path.exists():
                path.replace(backup)
        except OSError:
            pass
        return default if default is not None else {}


def save_json(path: Path, data: Any) -> None:
    _assert_runtime_write_allowed(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def append_jsonl(path: Path, row: dict) -> None:
    _assert_runtime_write_allowed(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, default=str) + "\n")
