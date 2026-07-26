"""Proof-builder handoff reporting (read-only)."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from doofus.core import doofus_paths
from doofus.core.doofus_paths import METRICS_DB
from doofus.proof.proof_builder_queue import queue_summary
from doofus.reports.run_window_telemetry_filter import read_jsonl


def handoff_report(*, generation: int | None = None) -> dict[str, Any]:
    summary = queue_summary()
    events = read_jsonl(doofus_paths.STATE / "proof_builder_queue_events.jsonl")
    gen_events = events
    if generation is not None:
        gen_events = [e for e in events if e.get("generation") == generation]

    conn = sqlite3.connect(METRICS_DB, timeout=30)
    if generation is not None:
        queued_candidates = conn.execute(
            "SELECT COUNT(*) FROM candidates WHERE generation=? AND rejection_reason LIKE '%queued_for_proof_builder%'",
            (generation,),
        ).fetchone()[0]
        total_candidates = conn.execute(
            "SELECT COUNT(*) FROM candidates WHERE generation=?", (generation,)
        ).fetchone()[0]
    else:
        queued_candidates = conn.execute(
            "SELECT COUNT(*) FROM candidates WHERE rejection_reason LIKE '%queued_for_proof_builder%'"
        ).fetchone()[0]
        total_candidates = conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0]
    conn.close()

    outcomes = summary.get("outcomes") or {}
    by_gen = summary.get("by_generation") or {}
    gen_key = str(generation) if generation is not None else None
    gen_queue_size = by_gen.get(gen_key, 0) if gen_key else summary.get("queue_size", 0)

    return {
        "classification": "DOOFUS_PROOF_BUILDER_HANDOFF_REPORT",
        "generation": generation,
        "queue_summary": summary,
        "queue_events_total": len(events),
        "queue_events_in_generation": len(gen_events),
        "candidates_queued_for_proof_builder_in_db": queued_candidates,
        "candidates_total_in_db": total_candidates,
        "queue_size_for_generation": gen_queue_size,
        "pending_in_queue": summary.get("pending", 0),
        "outcome_breakdown": outcomes,
        "handoff_status": "measured" if summary.get("enabled") else "disabled",
        "skipped_deferred_processed": {
            "pending": outcomes.get("pending", 0),
            "proof_partial": outcomes.get("proof_partial", 0),
            "proof_ready": outcomes.get("proof_ready", 0),
            "proof_failed": outcomes.get("proof_failed", 0),
            "proof_timeout": outcomes.get("proof_timeout", 0),
        },
    }
