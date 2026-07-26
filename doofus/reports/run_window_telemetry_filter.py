"""Filter JSONL telemetry events to the current live-cycle run window."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


DEFAULT_MARGIN = timedelta(minutes=2)


@dataclass
class RunWindowFilterResult:
    events_in_window: list[dict]
    events_excluded_as_stale: list[dict]
    stale_event_sources: dict[str, int] = field(default_factory=dict)
    run_window_start: str | None = None
    run_window_end: str | None = None
    run_window_filter_applied: bool = False
    run_id: str | None = None
    generation: int | None = None
    events_in_window_count: int = 0
    events_excluded_count: int = 0

    def to_summary_fields(self) -> dict[str, Any]:
        return {
            "run_window_start": self.run_window_start,
            "run_window_end": self.run_window_end,
            "run_window_filter_applied": self.run_window_filter_applied,
            "run_id": self.run_id,
            "generation": self.generation,
            "events_in_window": self.events_in_window_count,
            "events_excluded_as_stale": self.events_excluded_count,
            "stale_event_sources": self.stale_event_sources,
        }


def parse_event_timestamp(event: dict) -> datetime | None:
    raw = event.get("timestamp") or event.get("timestamp_utc")
    if not raw:
        return None
    try:
        text = str(raw).replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def normalize_run_bounds(
    start: datetime | str,
    end: datetime | str,
    *,
    margin: timedelta = DEFAULT_MARGIN,
) -> tuple[datetime, datetime]:
    if isinstance(start, str):
        start = datetime.fromisoformat(start)
    if isinstance(end, str):
        end = datetime.fromisoformat(end)
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    start = start.astimezone(timezone.utc) - margin
    end = end.astimezone(timezone.utc) + margin
    return start, end


def event_in_window(event: dict, *, window_start: datetime, window_end: datetime, run_id: str | None = None) -> bool:
    if run_id and event.get("run_id") == run_id:
        return True
    ts = parse_event_timestamp(event)
    if ts is None:
        return False
    return window_start <= ts <= window_end


def read_jsonl(path: Path, *, limit: int | None = None) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    if limit is not None:
        return rows[-limit:]
    return rows


def filter_events_by_run_window(
    events: list[dict],
    *,
    generation: int,
    window_start: datetime | str,
    window_end: datetime | str,
    source_name: str = "unknown",
    run_id: str | None = None,
    margin: timedelta = DEFAULT_MARGIN,
    fallback_tail: int = 30,
) -> RunWindowFilterResult:
    start, end = normalize_run_bounds(window_start, window_end, margin=margin)
    keyed = [e for e in events if e.get("generation") == generation]
    if run_id:
        by_run = [e for e in keyed if e.get("run_id") == run_id]
        if by_run:
            keyed = by_run
    in_window: list[dict] = []
    excluded: list[dict] = []
    for event in keyed:
        if event_in_window(event, window_start=start, window_end=end, run_id=run_id):
            in_window.append(event)
        else:
            excluded.append(event)
    if not in_window and keyed:
        in_window = keyed[-fallback_tail:]
        excluded = keyed[:-fallback_tail] if len(keyed) > fallback_tail else []
    stale_sources = {source_name: len(excluded)} if excluded else {}
    start_iso = start.astimezone().replace(microsecond=0).isoformat()
    end_iso = end.astimezone().replace(microsecond=0).isoformat()
    return RunWindowFilterResult(
        events_in_window=in_window,
        events_excluded_as_stale=excluded,
        stale_event_sources=stale_sources,
        run_window_start=start_iso,
        run_window_end=end_iso,
        run_window_filter_applied=True,
        run_id=run_id,
        generation=generation,
        events_in_window_count=len(in_window),
        events_excluded_count=len(excluded),
    )


def classify_init_watchdog(init_events: list[dict]) -> tuple[bool, str, float | None, str | None]:
    timeout_evt = next((e for e in init_events if e.get("step") == "cycle_init_timeout"), None)
    if timeout_evt:
        stalled = (timeout_evt.get("detail") or {}).get("stalled_step")
        return True, "timeout_aborted", timeout_evt.get("duration_ms"), stalled
    for e in reversed(init_events):
        if e.get("step") == "cycle_init_end" and e.get("duration_ms") is not None:
            return False, "ok", float(e["duration_ms"]), None
    return False, "ok", None, None


def classify_init_watchdog_unfiltered(init_events: list[dict], *, generation: int) -> tuple[bool, str]:
    keyed = [e for e in init_events if e.get("generation") == generation]
    timeout = any(e.get("step") == "cycle_init_timeout" for e in keyed)
    return timeout, "timeout_aborted" if timeout else "ok"


def stale_classification_impact(
    *,
    unfiltered_init_events: list[dict],
    filtered_init_events: list[dict],
    generation: int,
    pass_without_stale: bool,
) -> dict[str, Any]:
    unfiltered_timeout, unfiltered_status = classify_init_watchdog_unfiltered(unfiltered_init_events, generation=generation)
    filtered_timeout, filtered_status, _, _ = classify_init_watchdog(filtered_init_events)
    before = "DOOFUS_GEN1640_RETRY3_LIVE_VERIFICATION_PARTIAL" if unfiltered_timeout else (
        "DOOFUS_GEN1640_RETRY3_LIVE_VERIFICATION_PASS" if pass_without_stale else "DOOFUS_GEN1640_RETRY3_LIVE_VERIFICATION_PARTIAL"
    )
    after = "DOOFUS_GEN1640_RETRY3_LIVE_VERIFICATION_PARTIAL" if filtered_timeout else (
        "DOOFUS_GEN1640_RETRY3_LIVE_VERIFICATION_PASS" if pass_without_stale else "DOOFUS_GEN1640_RETRY3_LIVE_VERIFICATION_PARTIAL"
    )
    return {
        "classification_before_stale_filter": before,
        "classification_after_stale_filter": after,
        "stale_events_changed_classification": before != after,
        "init_watchdog_before_stale_filter": unfiltered_status,
        "init_watchdog_after_stale_filter": filtered_status,
    }
