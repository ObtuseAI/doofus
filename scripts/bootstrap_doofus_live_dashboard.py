"""Bootstrap B1010-B1016 live dashboard modules."""
from pathlib import Path

ROOT = Path(r"C:\sai-auth-doofus")

def w(rel: str, body: str) -> None:
    p = ROOT / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body.strip() + "\n", encoding="utf-8")

w("doofus/dashboard/live_metric_queries.py", '''
"""Safe SQLite queries for live dashboard."""
from __future__ import annotations
import sqlite3
from typing import Any
from doofus.core.doofus_paths import METRICS_DB
from doofus.core.doofus_state import init_db

DEFAULT_LIMIT = 500

def _connect() -> sqlite3.Connection | None:
    try:
        init_db()
        conn = sqlite3.connect(METRICS_DB, timeout=2.0)
        conn.row_factory = sqlite3.Row
        return conn
    except Exception:
        return None

def _rows(sql: str, params: tuple = (), limit: int = DEFAULT_LIMIT) -> list[dict[str, Any]]:
    conn = _connect()
    if not conn:
        return []
    try:
        cur = conn.execute(sql, params)
        out = [dict(r) for r in cur.fetchmany(limit)]
        conn.close()
        return out
    except sqlite3.Error:
        try:
            conn.close()
        except Exception:
            pass
        return []

def _scalar(sql: str, params: tuple = (), default: Any = 0) -> Any:
    conn = _connect()
    if not conn:
        return default
    try:
        row = conn.execute(sql, params).fetchone()
        conn.close()
        return row[0] if row and row[0] is not None else default
    except sqlite3.Error:
        try:
            conn.close()
        except Exception:
            pass
        return default

def count_table(table: str) -> int:
    return int(_scalar(f"SELECT COUNT(*) FROM {table}", default=0))

def recent_cycles(limit: int = DEFAULT_LIMIT) -> list[dict]:
    return _rows("SELECT * FROM cycles ORDER BY cycle_id DESC LIMIT ?", (limit,), limit)

def recent_candidates(limit: int = DEFAULT_LIMIT) -> list[dict]:
    return _rows("SELECT * FROM candidates ORDER BY created_at DESC LIMIT ?", (limit,), limit)

def recent_promotions(limit: int = DEFAULT_LIMIT) -> list[dict]:
    return _rows("SELECT * FROM promotions ORDER BY id DESC LIMIT ?", (limit,), limit)

def recent_rejections(limit: int = DEFAULT_LIMIT) -> list[dict]:
    return _rows("SELECT * FROM rejections ORDER BY id DESC LIMIT ?", (limit,), limit)

def recent_model_calls(limit: int = DEFAULT_LIMIT) -> list[dict]:
    return _rows("SELECT * FROM model_calls ORDER BY id DESC LIMIT ?", (limit,), limit)

def recent_safety_events(limit: int = DEFAULT_LIMIT) -> list[dict]:
    return _rows("SELECT * FROM safety_events ORDER BY id DESC LIMIT ?", (limit,), limit)

def recent_heartbeats(limit: int = DEFAULT_LIMIT) -> list[dict]:
    return _rows("SELECT * FROM heartbeats ORDER BY id DESC LIMIT ?", (limit,), limit)

def recent_dashboard_events(limit: int = DEFAULT_LIMIT) -> list[dict]:
    return _rows("SELECT * FROM dashboard_events ORDER BY id DESC LIMIT ?", (limit,), limit)

def score_by_generation(limit: int = DEFAULT_LIMIT) -> list[dict]:
    return _rows(
        """SELECT generation,
           COUNT(*) AS count,
           AVG(score_total) AS avg_total,
           MAX(score_total) AS best_total,
           AVG(score_compounding) AS avg_compounding,
           AVG(score_recursive_learning) AS avg_recursive,
           AVG(score_generalization) AS avg_generalization,
           AVG(score_replay) AS avg_replay,
           AVG(score_safety) AS avg_safety
           FROM candidates GROUP BY generation ORDER BY generation LIMIT ?""",
        (limit,),
        limit,
    )

def rejection_reason_counts(limit: int = DEFAULT_LIMIT) -> list[dict]:
    return _rows(
        "SELECT reason, COUNT(*) AS count FROM rejections GROUP BY reason ORDER BY count DESC LIMIT ?",
        (limit,),
        limit,
    )

def mutation_type_counts(limit: int = DEFAULT_LIMIT) -> list[dict]:
    return _rows(
        "SELECT mutation_type, COUNT(*) AS count FROM candidates GROUP BY mutation_type ORDER BY count DESC LIMIT ?",
        (limit,),
        limit,
    )

def candidate_status_counts() -> list[dict]:
    return _rows("SELECT status, COUNT(*) AS count FROM candidates GROUP BY status")

def model_calls_timeseries(limit: int = DEFAULT_LIMIT) -> list[dict]:
    return _rows("SELECT id, model, provider, tokens_est, cost_est, created_at FROM model_calls ORDER BY id DESC LIMIT ?", (limit,), limit)

def promotions_over_time(limit: int = DEFAULT_LIMIT) -> list[dict]:
    return _rows("SELECT created_at FROM promotions ORDER BY id DESC LIMIT ?", (limit,), limit)

def rejections_over_time(limit: int = DEFAULT_LIMIT) -> list[dict]:
    return _rows("SELECT created_at, reason FROM rejections ORDER BY id DESC LIMIT ?", (limit,), limit)

def arena_results(limit: int = DEFAULT_LIMIT) -> list[dict]:
    return _rows("SELECT * FROM arena_results ORDER BY id DESC LIMIT ?", (limit,), limit)

def top_candidates(limit: int = 20) -> list[dict]:
    return _rows("SELECT * FROM candidates ORDER BY score_total DESC LIMIT ?", (limit,), limit)

def lineage_rows(limit: int = DEFAULT_LIMIT) -> list[dict]:
    return _rows(
        "SELECT candidate_id, parent_id, generation, score_total, status FROM candidates WHERE parent_id IS NOT NULL ORDER BY generation DESC LIMIT ?",
        (limit,),
        limit,
    )
''')

w("doofus/dashboard/live_state_reader.py", '''
"""Read runtime JSON state for dashboard."""
from __future__ import annotations
import json
from doofus.core.doofus_paths import STATE, CONTROL, RUN_ENABLED, STOP_REQUEST, EMERGENCY_STOP
from doofus.supervisor.doofus_crash_recovery import load_checkpoint
from doofus.supervisor.doofus_cycle_checkpoint import read_checkpoint
from doofus.safety.on_off_switch import status as switch_status

def read_control_state() -> dict:
    return switch_status()

def read_checkpoint_status() -> dict:
    cp = read_checkpoint()
    legacy = load_checkpoint()
    return {"cycle_checkpoint": cp, "legacy_checkpoint": legacy}

def read_latest_error() -> str:
    cp = read_checkpoint()
    err = cp.get("data", {}).get("last_error", "")
    if err:
        return str(err)[:500]
    data = cp.get("data", {})
    mr = data.get("classification") or data.get("model_result", {})
    if isinstance(mr, dict):
        e = mr.get("error", "")
        if e:
            from doofus.model_router.model_secret_redactor import redact_secrets
            return redact_secrets(str(e))[:500]
    return ""
''')

w("doofus/dashboard/live_task_reader.py", '''
"""Scheduled task status for dashboard."""
from __future__ import annotations
import subprocess

TASKS = ("Doofus-24-7-Supervisor", "Doofus-Local-Dashboard")

def get_task_status() -> dict:
    out = {}
    for name in TASKS:
        r = subprocess.run(["schtasks", "/Query", "/TN", name, "/FO", "LIST"], capture_output=True, text=True)
        state = "unknown"
        if r.returncode == 0:
            for line in r.stdout.splitlines():
                if line.strip().startswith("Status:"):
                    state = line.split(":", 1)[1].strip()
        out[name] = {"registered": r.returncode == 0, "state": state}
    return out
''')

w("doofus/dashboard/live_chart_models.py", '''
"""Chart payload models."""
from __future__ import annotations
from dataclasses import dataclass, field

@dataclass
class LineSeries:
    title: str
    xs: list
    ys: list
    empty_label: str = "No data yet"

@dataclass
class BarSeries:
    title: str
    labels: list
    values: list
    empty_label: str = "No data yet"

@dataclass
class ChartBundle:
    classification: str = "DOOFUS_LIVE_CHART_BUNDLE"
    lines: list[LineSeries] = field(default_factory=list)
    bars: list[BarSeries] = field(default_factory=list)

def empty_line(title: str) -> LineSeries:
    return LineSeries(title=title, xs=[], ys=[])

def empty_bar(title: str) -> BarSeries:
    return BarSeries(title=title, labels=[], values=[])
''')

print("bootstrap part 1 ok")
