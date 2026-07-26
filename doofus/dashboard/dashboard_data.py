"""Dashboard data queries."""
from __future__ import annotations
import sqlite3
from doofus.core.doofus_paths import METRICS_DB
from doofus.safety.on_off_switch import status as switch_status
from doofus.safety.budget_guard import check_budget
from doofus.core.doofus_config import DoofusConfig
from doofus.supervisor.doofus_crash_recovery import load_checkpoint

_EMPTY = {
    "candidate_count": 0,
    "promotion_count": 0,
    "rejection_count": 0,
    "mutation_count": 0,
    "model_call_count": 0,
    "last_heartbeat": None,
}


def _conn(*, timeout: float = 2.0) -> sqlite3.Connection:
    from doofus.core.metrics_db import connect_metrics_db
    return connect_metrics_db(timeout=timeout)


def summary(*, fast: bool = False) -> dict:
    cp = load_checkpoint()
    cfg = DoofusConfig.from_env()
    sw = switch_status()
    cand = prom = rej = mut = mc = 0
    hb = None
    db_timeout = 0.4 if fast else 2.0
    try:
        c = _conn(timeout=db_timeout)
        cand = c.execute("SELECT COUNT(*) FROM candidates").fetchone()[0]
        prom = c.execute("SELECT COUNT(*) FROM promotions").fetchone()[0]
        rej = c.execute("SELECT COUNT(*) FROM rejections").fetchone()[0]
        mut = c.execute("SELECT COUNT(*) FROM mutations").fetchone()[0]
        mc = c.execute("SELECT COUNT(*) FROM model_calls").fetchone()[0]
        hb = c.execute("SELECT created_at, status FROM heartbeats ORDER BY id DESC LIMIT 1").fetchone()
        c.close()
    except sqlite3.OperationalError:
        pass
    try:
        budget = check_budget(cfg)
    except Exception:
        budget = {"ok": True, "calls_last_hour": 0, "daily_cost_est": 0.0}
    return {
        "switch": sw,
        "budget": budget,
        "candidate_count": cand,
        "promotion_count": prom,
        "rejection_count": rej,
        "mutation_count": mut,
        "model_call_count": mc,
        "generation": cp.get("generation", 0),
        "run_id": cp.get("run_id"),
        "baseline_score": cp.get("baseline_score", 0.5),
        "model_mode": cfg.model_mode,
        "model_name": cfg.model_name,
        "last_heartbeat": {"at": hb[0], "status": hb[1]} if hb else None,
    }

def chart_series() -> dict:
    c = _conn()
    gens = c.execute("SELECT generation, COUNT(*) FROM cycles GROUP BY generation ORDER BY generation").fetchall()
    scores = c.execute("SELECT generation, AVG(score_total), MAX(score_total) FROM candidates GROUP BY generation ORDER BY generation").fetchall()
    rej = c.execute("SELECT reason, COUNT(*) FROM rejections GROUP BY reason").fetchall()
    prom_ts = c.execute("SELECT created_at FROM promotions ORDER BY id").fetchall()
    c.close()
    return {
        "variants_by_generation": [{"generation": g, "count": n} for g, n in gens],
        "avg_score_by_generation": [{"generation": g, "avg": a, "best": b} for g, a, b in scores],
        "rejection_reasons": [{"reason": r, "count": n} for r, n in rej],
        "promotions_over_time": [p[0] for p in prom_ts],
    }
