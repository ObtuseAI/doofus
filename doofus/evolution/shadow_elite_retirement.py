"""Retire shadow elites after repeated proof failure."""
from __future__ import annotations

import json
from pathlib import Path

from doofus.core.doofus_paths import STATE

ARCHIVE = STATE / "shadow_elite_archive.json"
FAILURES = STATE / "shadow_elite_failures.json"
MAX_FAILURES = 5


def _load_failures() -> dict:
    if not FAILURES.exists():
        return {}
    return json.loads(FAILURES.read_text(encoding="utf-8"))


def _save_failures(data: dict) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    FAILURES.write_text(json.dumps(data, indent=2), encoding="utf-8")


def record_failure(candidate_id: str) -> int:
    data = _load_failures()
    data[candidate_id] = int(data.get(candidate_id, 0)) + 1
    _save_failures(data)
    if data[candidate_id] >= MAX_FAILURES:
        retire(candidate_id)
    return data[candidate_id]


def retire(candidate_id: str) -> None:
    if not ARCHIVE.exists():
        return
    entries = json.loads(ARCHIVE.read_text(encoding="utf-8"))
    for e in entries:
        if e.get("candidate_id") == candidate_id:
            e["status"] = "retired"
    ARCHIVE.write_text(json.dumps(entries, indent=2), encoding="utf-8")


def failure_summary() -> dict:
    data = _load_failures()
    return {"tracked": len(data), "max_failures": MAX_FAILURES}
