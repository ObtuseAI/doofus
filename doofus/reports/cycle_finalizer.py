"""Shared finalization helpers for controlled-cycle artifact writers."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from doofus.reports.run_window_telemetry_filter import (
    classify_init_watchdog,
    filter_events_by_run_window,
    read_jsonl,
    stale_classification_impact,
)

__all__ = [
    "write_artifact_pair",
    "load_telemetry_sources",
    "filter_all_telemetry",
    "classify_init_watchdog",
    "filter_events_by_run_window",
    "read_jsonl",
    "stale_classification_impact",
]


def write_artifact_pair(output_dir: Path, stem: str, payload: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / f"{stem}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    lines = [f"# {stem.replace('_', ' ').title()}", ""]
    if "classification" in payload:
        lines.append(f"**Classification:** `{payload['classification']}`")
        lines.append("")
    for key, value in payload.items():
        if key == "classification":
            continue
        if isinstance(value, (dict, list)):
            lines.extend([f"## {key}", "", "```json", json.dumps(value, indent=2)[:14000], "```", ""])
        else:
            lines.append(f"- **{key}**: `{value}`")
    (output_dir / f"{stem}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_telemetry_sources(state_dir: Path) -> dict[str, list[dict[str, Any]]]:
    names = (
        "cycle_init_events.jsonl",
        "inline_rescue_events.jsonl",
        "high_score_miner_events.jsonl",
        "shadow_upgrade_events.jsonl",
        "supervisor_phase_events.jsonl",
        "scoring_step_events.jsonl",
    )
    return {name: read_jsonl(state_dir / name) for name in names}


def filter_all_telemetry(
    *,
    state_dir: Path,
    generation: int,
    window_start,
    window_end,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Apply run-window filter to all standard telemetry sources."""
    sources = load_telemetry_sources(state_dir)
    filtered: dict[str, Any] = {}
    total_excluded = 0
    stale_sources: dict[str, int] = {}
    for name, events in sources.items():
        result = filter_events_by_run_window(
            events,
            generation=generation,
            window_start=window_start,
            window_end=window_end,
            source_name=name,
            run_id=run_id,
        )
        filtered[name] = result
        stale_sources.update(result.stale_event_sources)
        total_excluded += result.events_excluded_count
    return {
        "filtered": filtered,
        "events_excluded_as_stale_total": total_excluded,
        "stale_event_sources": stale_sources,
    }
