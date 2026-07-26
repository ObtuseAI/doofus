"""Read-only observability audits for inline rescue and proof-builder."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from doofus.core.doofus_paths import STATE


def _read_jsonl(path: Path, limit: int = 2000) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]:
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def audit_inline_rescue(generation: int | None = 1639) -> dict[str, Any]:
    events = _read_jsonl(STATE / "inline_rescue_events.jsonl")
    if generation is not None:
        events = [e for e in events if e.get("generation") == generation]
    stages: dict[str, int] = {}
    skip_reasons: dict[str, int] = {}
    for e in events:
        stage = str(e.get("stage", "unknown"))
        stages[stage] = stages.get(stage, 0) + 1
        if e.get("status") == "skipped":
            reason = str(e.get("detail", {}).get("reason", e.get("event_type", "skip")))
            skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
    return {
        "classification": "DOOFUS_INLINE_RESCUE_OBSERVABILITY_AUDIT",
        "generation_filter": generation,
        "event_count": len(events),
        "stage_counts": stages,
        "skip_reasons": skip_reasons,
        "timeout_events": sum(1 for e in events if e.get("event_type") == "timeout"),
        "proof_builder_skipped_deadline": skip_reasons.get("skip", 0)
        + sum(1 for e in events if e.get("stage") == "proof_builder_start" and e.get("status") == "skipped"),
        "recommendations": [
            "Surface proof_builder_skipped when remaining_seconds <= 1.0 in cycle summary.",
            "Aggregate shadow_upgrade deadline status per generation.",
            "Add per-stage duration_ms rollup to generation summary.",
        ],
    }


def audit_proof_builder(generation: int | None = 1639) -> dict[str, Any]:
    queue_path = STATE / "proof_builder_queue.json"
    stats_path = STATE / "proof_builder_stats.json"
    events = _read_jsonl(STATE / "proof_builder_queue_events.jsonl")
    if generation is not None:
        events = [e for e in events if e.get("generation") == generation]

    queue_size = 0
    outcomes: dict[str, int] = {}
    if queue_path.exists():
        try:
            entries = json.loads(queue_path.read_text(encoding="utf-8"))
            queue_size = len(entries)
            for e in entries:
                o = str(e.get("outcome", "pending"))
                outcomes[o] = outcomes.get(o, 0) + 1
        except json.JSONDecodeError:
            pass

    stats = {}
    if stats_path.exists():
        try:
            stats = json.loads(stats_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass

    skip_events = [e for e in events if "skip" in str(e.get("event_type", "")).lower()]
    return {
        "classification": "DOOFUS_PROOF_BUILDER_OBSERVABILITY_AUDIT",
        "generation_filter": generation,
        "queue_size": queue_size,
        "queue_outcomes": outcomes,
        "stats": stats,
        "queue_event_count": len(events),
        "skip_event_count": len(skip_events),
        "skip_reasons_sample": [e.get("reason") for e in skip_events[:10]],
        "recommendations": [
            "Add proof_builder_skipped_count to generation summary.",
            "Normalize skip reason taxonomy: deadline_reserve, modes_disabled, generation_mismatch.",
            "Expose queued-for-proof count in compact cycle ledger.",
        ],
    }
