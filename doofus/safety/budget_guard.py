"""Budget and rate guards."""
from __future__ import annotations
import sqlite3
from datetime import datetime, timezone, timedelta
from doofus.core.doofus_config import DoofusConfig
from doofus.core.doofus_paths import METRICS_DB

def _conn():
    return sqlite3.connect(METRICS_DB, timeout=2.0)

def model_calls_last_hour() -> int:
    since = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    c = _conn()
    n = c.execute("SELECT COUNT(*) FROM model_calls WHERE created_at >= ?", (since,)).fetchone()[0]
    c.close()
    return n

def estimated_daily_cost() -> float:
    since = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    c = _conn()
    row = c.execute("SELECT COALESCE(SUM(cost_est),0) FROM model_calls WHERE created_at >= ?", (since,)).fetchone()
    c.close()
    return float(row[0])

def check_budget(cfg: DoofusConfig | None = None) -> dict:
    cfg = cfg or DoofusConfig.from_env()
    calls = model_calls_last_hour()
    cost = estimated_daily_cost()
    ok = calls < cfg.max_model_calls_per_hour and cost < cfg.max_daily_cost_usd
    return {
        "ok": ok,
        "calls_last_hour": calls,
        "max_calls_per_hour": cfg.max_model_calls_per_hour,
        "daily_cost_est": cost,
        "max_daily_cost_usd": cfg.max_daily_cost_usd,
    }
