"""Discover operator Desktop doofusapi secret sources."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from doofus.model_router.openrouter_secret_source import read_secret_file
from doofus.safety.secret_guard import assert_no_secret_in_payload

DESKTOP_CANDIDATES: tuple[Path, ...] = (
    Path(r"C:\Users\developer\Desktop\doofusapi"),
    Path(r"C:\Users\developer\Desktop\doofusapi.txt"),
    Path(r"C:\Users\developer\Desktop\doofusapi.env"),
    Path(r"C:\Users\developer\OneDrive\Desktop\doofusapi"),
    Path(r"C:\Users\developer\OneDrive\Desktop\doofusapi.txt"),
    Path(r"C:\Users\developer\OneDrive\Desktop\doofusapi.env"),
)


def discover_desktop_paths() -> list[Path]:
    found: list[Path] = []
    seen: set[str] = set()
    for base in DESKTOP_CANDIDATES:
        key = str(base).lower()
        if key in seen:
            continue
        seen.add(key)
        if base.is_file():
            found.append(base)
        elif base.is_dir():
            for child in sorted(base.iterdir()):
                if child.is_file():
                    found.append(child)
    return found


def load_desktop_secret() -> dict:
    """Return safe metadata; includes internal _value when found (not for reports)."""
    paths = discover_desktop_paths()
    checked: list[str] = []
    for path in paths:
        checked.append(str(path))
        meta = read_secret_file(path)
        if meta.get("secret_found"):
            meta["checked_paths"] = checked
            return meta
    return {
        "secret_found": False,
        "secret_source_type": "missing",
        "secret_source_path": checked[0] if checked else str(DESKTOP_CANDIDATES[0]),
        "secret_length_bucket": "unknown",
        "key_shape": "unknown",
        "secret_value": "REDACTED",
        "checked_paths": checked,
    }


def get_desktop_secret_value() -> str | None:
    meta = load_desktop_secret()
    return meta.get("_value")


def safe_report(meta: dict) -> dict:
    out = {k: v for k, v in meta.items() if not k.startswith("_")}
    return assert_no_secret_in_payload(out)


def main() -> int:
    meta = load_desktop_secret()
    report = safe_report(meta)
    print(json.dumps(report, indent=2))
    if meta.get("secret_found"):
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
