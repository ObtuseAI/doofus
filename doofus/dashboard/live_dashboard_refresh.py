"""Centralized dashboard refresh — 30s live update with chart cache."""
from __future__ import annotations
import sqlite3
import time
from doofus.core.doofus_events import utc_now
from doofus.core.doofus_paths import METRICS_DB
from doofus.core.metrics_db import connect_metrics_db

REFRESH_INTERVAL_SECONDS = 30
_chart_cache: dict = {"figures": {}, "built_at": 0.0, "ttl": 25.0}


def record_dashboard_refresh(detail: str = "live_refresh") -> None:
    try:
        conn = connect_metrics_db(timeout=1.0)
        conn.execute(
            "INSERT INTO dashboard_events (event_type, detail, created_at) VALUES (?,?,?)",
            ("dashboard_refresh", detail, utc_now()),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass

def collect_all_charts(*, force: bool = False) -> dict[str, object]:
    now = time.monotonic()
    if not force and _chart_cache["figures"] and (now - _chart_cache["built_at"]) < _chart_cache["ttl"]:
        return dict(_chart_cache["figures"])

    from doofus.dashboard.live_mutation_charts import build_mutation_charts
    from doofus.dashboard.live_candidate_charts import build_candidate_charts
    from doofus.dashboard.live_lineage_charts import build_lineage_charts
    from doofus.dashboard.live_score_charts import build_score_charts
    from doofus.dashboard.live_compounding_charts import build_compounding_charts
    from doofus.dashboard.live_recursive_learning_charts import build_recursive_learning_charts
    from doofus.dashboard.live_improvement_charts import build_improvement_charts
    from doofus.dashboard.live_model_charts import build_model_charts
    from doofus.dashboard.live_budget_charts import build_budget_charts
    from doofus.dashboard.live_safety_charts import build_safety_charts
    from doofus.dashboard.live_arena_charts import build_arena_charts
    from doofus.dashboard.live_map_elites_charts import build_map_elites_charts
    from doofus.dashboard.live_gepa_trace_charts import build_gepa_trace_charts
    from doofus.dashboard.live_gep_charts import build_gep_charts
    from doofus.dashboard.live_metacognition_charts import build_metacognition_charts

    out: dict[str, object] = {}
    builders = [
        ("mutation", build_mutation_charts),
        ("candidate", build_candidate_charts),
        ("lineage", build_lineage_charts),
        ("score", build_score_charts),
        ("compounding", build_compounding_charts),
        ("recursive", build_recursive_learning_charts),
        ("improvement", build_improvement_charts),
        ("model", build_model_charts),
        ("budget", build_budget_charts),
        ("safety", build_safety_charts),
        ("arena", build_arena_charts),
        ("map", build_map_elites_charts),
        ("gepa", build_gepa_trace_charts),
        ("gep", build_gep_charts),
        ("metacognition", build_metacognition_charts),
    ]
    for prefix, fn in builders:
        for name, fig in fn().items():
            if hasattr(fig, "update_layout"):
                out[f"{prefix}.{name}"] = fig
    _chart_cache["figures"] = out
    _chart_cache["built_at"] = now
    return dict(out)

def invalidate_chart_cache() -> None:
    _chart_cache["built_at"] = 0.0
