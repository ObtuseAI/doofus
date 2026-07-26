"""Structured arena result schema."""
from __future__ import annotations

from typing import Any


def normalize_arena_result(raw: dict[str, Any]) -> dict[str, Any]:
    cid = raw.get("candidate_id")
    arena = raw.get("arena")
    if not cid or not arena:
        raise ValueError("arena result requires candidate_id and arena")
    score = float(raw.get("score", 0.0))
    passed = raw.get("passed")
    if passed is None:
        passed = str(raw.get("result", "")).startswith("pass")
    outcome = "pass" if passed else "fail"
    arena_score = round(max(0.0, min(1.0, score)), 4)
    return {
        "candidate_id": cid,
        "arena": arena,
        "result": raw.get("result") or f"{outcome}:{arena_score}",
        "score": arena_score,
        "steps": int(raw.get("steps") or 0),
        "trace_ref": raw.get("trace_ref") or "",
        "passed": passed,
        "mode": raw.get("mode", ""),
        "created_at": raw.get("created_at"),
    }


def parse_result_string(result: str) -> tuple[bool, float]:
    if ":" in result:
        prefix, val = result.split(":", 1)
        try:
            return prefix.strip().lower() == "pass", float(val)
        except ValueError:
            return prefix.strip().lower() == "pass", 0.0
    return result.startswith("pass"), 0.0
