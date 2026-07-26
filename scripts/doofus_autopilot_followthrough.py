"""Generate agent follow-through report after each autopilot session."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

LAST = ROOT / "runtime" / "state" / "autopilot_last.json"
HEARTBEAT = ROOT / "runtime" / "state" / "autopilot_scheduler_heartbeat.json"
REPORT = ROOT / "runtime" / "state" / "autopilot_followthrough.json"
REPORT_MD = ROOT / "runtime" / "state" / "autopilot_followthrough.md"
SESSION_LOG = ROOT / "runtime" / "state" / "autopilot_sessions.jsonl"
SCHEDULER_PID = ROOT / "runtime" / "state" / "autopilot_scheduler.pid"


def _utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_scheduler_pid() -> int | None:
    if not SCHEDULER_PID.exists():
        return None
    try:
        raw = SCHEDULER_PID.read_text(encoding="utf-8-sig").strip()
        return int(raw) if raw else None
    except ValueError:
        return None


def _scheduler_alive() -> bool:
    pid = _read_scheduler_pid()
    if not pid or pid <= 0:
        return False
    try:
        import os
        os.kill(pid, 0)
        return True
    except OSError:
        if sys.platform == "win32":
            import ctypes
            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
                return True
        return False


def _session_count_today() -> int:
    if not SESSION_LOG.exists():
        return 0
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    n = 0
    for line in SESSION_LOG.read_text(encoding="utf-8", errors="replace").splitlines()[-50:]:
        if "AUTOPILOT_SESSION_COMPLETE" not in line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if str(row.get("ended_at", "")).startswith(today):
            n += 1
    return n


def _actions_summary(last: dict) -> list[str]:
    actions: list[str] = []
    for tick in _iter_session_ticks(last.get("session_id", "")):
        for act in (tick.get("improve") or {}).get("actions") or []:
            name = act.get("action", "?")
            result = act.get("result")
            if isinstance(result, dict):
                detail = result.get("classification") or result.get("escalated")
            else:
                detail = act.get("result") or act.get("error")
            actions.append(f"{name}: {detail}")
    return actions


def _iter_session_ticks(session_id: str):
    if not session_id or not SESSION_LOG.exists():
        return
    lines = SESSION_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
    for line in lines[-200:]:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("session_id") == session_id and "watch" in row:
            yield row


def build_report() -> dict:
    last = {}
    if LAST.exists():
        try:
            last = json.loads(LAST.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass

    hb = {}
    if HEARTBEAT.exists():
        try:
            hb = json.loads(HEARTBEAT.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass

    evaluate = (last.get("last_tick") or {}).get("evaluate") or {}
    pressure = evaluate.get("pressure") or {}
    map_elites = evaluate.get("map_elites") or {}
    top = (map_elites.get("top_cells") or [{}])[0]

    report = {
        "generated_at": _utc(),
        "scheduler_alive": _scheduler_alive(),
        "scheduler_pid": _read_scheduler_pid(),
        "scheduler_phase": hb.get("phase"),
        "sessions_completed_today": _session_count_today(),
        "last_session": {
            "session_id": last.get("session_id"),
            "started_at": last.get("started_at"),
            "ended_at": last.get("ended_at"),
            "wall_clock_seconds": last.get("wall_clock_seconds"),
            "ticks": last.get("ticks"),
            "generation": ((last.get("last_tick") or {}).get("watch") or {}).get("metrics", {}).get("generation"),
            "stagnation_cycles": pressure.get("stagnation_cycles"),
            "last_promotion_generation": pressure.get("last_promotion_generation"),
            "map_elites_cells": map_elites.get("cell_count"),
            "top_fitness": top.get("fitness"),
            "top_candidate": top.get("candidate_id"),
            "issues": evaluate.get("issues") or [],
            "cleanup_killed": len((last.get("session_cleanup") or {}).get("killed") or []),
        },
        "actions_this_session": _actions_summary(last),
        "next_session_eta": "after 40min idle from last session end" if hb.get("phase") == "idle" else "in session or starting",
    }
    return report


def _to_markdown(report: dict) -> str:
    ls = report.get("last_session") or {}
    lines = [
        f"# Autopilot Follow-Through — {report.get('generated_at')}",
        "",
        "## Scheduler",
        f"- **Alive:** {report.get('scheduler_alive')}",
        f"- **PID:** {report.get('scheduler_pid')}",
        f"- **Phase:** {report.get('scheduler_phase')}",
        f"- **Sessions completed today:** {report.get('sessions_completed_today')}",
        "",
        "## Last Session",
        f"- **ID:** {ls.get('session_id')}",
        f"- **Window:** {ls.get('started_at')} → {ls.get('ended_at')} ({ls.get('wall_clock_seconds')}s wall)",
        f"- **Ticks:** {ls.get('ticks')}",
        f"- **Generation:** {ls.get('generation')}",
        f"- **Stagnation:** {ls.get('stagnation_cycles')} cycles (last promo gen {ls.get('last_promotion_generation')})",
        f"- **MAP-Elites:** {ls.get('map_elites_cells')} cells, top fitness **{ls.get('top_fitness')}** ({ls.get('top_candidate')})",
        f"- **Issues:** {', '.join(ls.get('issues') or []) or 'none'}",
        f"- **Cleanup killed:** {ls.get('cleanup_killed')} processes",
        "",
        "## Actions This Session",
    ]
    for act in report.get("actions_this_session") or []:
        lines.append(f"- {act}")
    if not report.get("actions_this_session"):
        lines.append("- (none recorded)")
    lines.extend(["", f"**Next session:** {report.get('next_session_eta')}"])
    return "\n".join(lines) + "\n"


def main() -> int:
    report = build_report()
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    REPORT_MD.write_text(_to_markdown(report), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
