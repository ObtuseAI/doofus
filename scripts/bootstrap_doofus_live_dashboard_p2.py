"""Bootstrap B1011-B1016 panels, charts, app helpers."""
from pathlib import Path

ROOT = Path(r"C:\sai-auth-doofus")

def w(rel: str, body: str) -> None:
    p = ROOT / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body.strip() + "\n", encoding="utf-8")

# B1011 panels
for name, imp, fn in [
    ("live_status_panel.py", "get_status_cards, get_live_counters, get_heartbeat_status", "def build_status_panel() -> dict:\n    return {'cards': get_status_cards(), 'counters': get_live_counters(), 'heartbeat': get_heartbeat_status()}"),
    ("live_control_panel.py", "read_control_state", "def build_control_panel() -> dict:\n    return {'switch': read_control_state(), 'writes_files_only': True}"),
    ("live_supervisor_panel.py", "get_task_status, get_heartbeat_status, get_checkpoint_status", "def build_supervisor_panel() -> dict:\n    return {'tasks': get_task_status(), 'heartbeat': get_heartbeat_status(), 'checkpoint': get_checkpoint_status()}"),
    ("live_model_status_panel.py", "get_model_auth_status, get_budget_rate_status, get_model_call_timeseries", "def build_model_status_panel() -> dict:\n    return {'auth': get_model_auth_status(), 'budget': get_budget_rate_status(), 'recent_calls': get_model_call_timeseries()[:10]}"),
    ("live_safety_panel.py", "get_safety_events, get_rejection_reason_counts", "def build_safety_panel() -> dict:\n    return {'events': get_safety_events(), 'rejection_reasons': get_rejection_reason_counts()}"),
]:
    w(f"doofus/dashboard/{name}", f'''"""Live dashboard panel."""
from __future__ import annotations
from doofus.dashboard.live_data_api import {imp}

{fn}
''')

# Chart helper base
CHART_HELPER = '''
from doofus.dashboard.dashboard_charts import line_chart, plot_chart
from doofus.dashboard.live_chart_models import empty_line, empty_bar, ChartBundle

def _plot(title, rows, xk, yk):
    if not rows:
        return plot_chart(title, [], [])
    xs = [r.get(xk) for r in rows]
    ys = [float(r.get(yk) or 0) for r in rows]
    return plot_chart(title, xs, ys)

def _line(title, rows, xk, yk):
    return _plot(title, rows, xk, yk)

def _bar(title, rows, lk, vk):
    return _plot(title, rows, lk, vk)
'''

w("doofus/dashboard/live_mutation_charts.py", CHART_HELPER + '''
from doofus.dashboard.live_data_api import get_candidate_generation_timeseries, get_rejection_reason_counts
from doofus.dashboard import live_metric_queries as mq

def build_mutation_charts():
    gens = get_candidate_generation_timeseries()
    muts = mq.mutation_type_counts()
    status = mq.candidate_status_counts()
    return {
        "candidates_by_generation": _bar("Candidates by generation", gens, "generation", "count"),
        "mutation_types": _bar("Mutation type counts", muts, "mutation_type", "count"),
        "status_distribution": _bar("Candidate status", status, "status", "count"),
        "variants_line": _line("Average score by generation", gens, "generation", "avg_total"),
    }
''')

w("doofus/dashboard/live_candidate_charts.py", CHART_HELPER + '''
from doofus.dashboard import live_metric_queries as mq

def build_candidate_charts():
    top = mq.top_candidates(20)
    gens = mq.score_by_generation()
    return {
        "top_scores": _bar("Top candidates by score", top, "candidate_id", "score_total"),
        "best_by_gen": _line("Best score by generation", gens, "generation", "best_total"),
    }
''')

w("doofus/dashboard/live_lineage_charts.py", CHART_HELPER + '''
from doofus.dashboard.live_data_api import get_candidate_lineage_rows

def build_lineage_charts():
    rows = get_candidate_lineage_rows()
    depth = {}
    for r in rows:
        g = r.get("generation", 0)
        depth[g] = depth.get(g, 0) + 1
    dr = [{"generation": k, "count": v} for k, v in sorted(depth.items())]
    return {"lineage_depth": _bar("Lineage depth by generation", dr, "generation", "count")}
''')

w("doofus/dashboard/live_score_charts.py", CHART_HELPER + '''
from doofus.dashboard import live_metric_queries as mq

def build_score_charts():
    g = mq.score_by_generation()
    return {
        "avg_score": _line("Average score by generation", g, "generation", "avg_total"),
        "best_score": _line("Best score by generation", g, "generation", "best_total"),
        "safety": _line("Safety score by generation", g, "generation", "avg_safety"),
        "replay": _line("Replay stability by generation", g, "generation", "avg_replay"),
        "generalization": _line("Generalization by generation", g, "generation", "avg_generalization"),
    }
''')

w("doofus/dashboard/live_compounding_charts.py", CHART_HELPER + '''
from doofus.dashboard.live_data_api import get_compounding_timeseries

def build_compounding_charts():
    rows = get_compounding_timeseries()
    return {"compounding": _line("Compounding score (local heuristic)", rows, "generation", "value")}
''')

w("doofus/dashboard/live_recursive_learning_charts.py", CHART_HELPER + '''
from doofus.dashboard.live_data_api import get_recursive_learning_timeseries

def build_recursive_learning_charts():
    rows = get_recursive_learning_timeseries()
    return {"recursive_learning": _line("Recursive learning score (local heuristic)", rows, "generation", "value")}
''')

w("doofus/dashboard/live_improvement_charts.py", CHART_HELPER + '''
from doofus.dashboard.live_data_api import get_promotion_rejection_timeseries
from doofus.dashboard import live_metric_queries as mq

def build_improvement_charts():
    pr = get_promotion_rejection_timeseries()
    prom = [{"i": i} for i, _ in enumerate(reversed(pr.get("promotions", [])))]
    rej = [{"i": i} for i, _ in enumerate(reversed(pr.get("rejections", [])))]
    gens = mq.score_by_generation()
    return {
        "promotion_trend": _line("Promotion index trend", prom, "i", "i") if prom else _line("Promotions over time", [], "i", "i"),
        "rejection_trend": _line("Rejection index trend", rej, "i", "i") if rej else _line("Rejections over time", [], "i", "i"),
        "improvement_delta": _line("Best score trend", gens, "generation", "best_total"),
    }
''')

w("doofus/dashboard/live_model_charts.py", CHART_HELPER + '''
from doofus.dashboard.live_data_api import get_model_call_timeseries, get_model_auth_status

def build_model_charts():
    calls = get_model_call_timeseries()
    cost_rows = [{"id": c.get("id"), "cost": float(c.get("cost_est") or 0)} for c in reversed(calls)]
    auth = get_model_auth_status()
    return {
        "model_calls": _line("Model calls (by id)", [{"id": c.get("id"), "n": 1} for c in reversed(calls)], "id", "n"),
        "estimated_cost": _line("Estimated cost", cost_rows, "id", "cost"),
        "auth_note": auth,
    }
''')

w("doofus/dashboard/live_budget_charts.py", CHART_HELPER + '''
from doofus.dashboard.live_data_api import get_budget_rate_status

def build_budget_charts():
    b = get_budget_rate_status()
    rows = [
        {"label": "used", "value": float(b.get("daily_cost_est", 0))},
        {"label": "remaining", "value": float(b.get("budget_remaining_usd", 0))},
    ]
    rate = [
        {"label": "calls", "value": int(b.get("calls_last_hour", 0))},
        {"label": "remaining", "value": int(b.get("calls_remaining_hour", 0))},
    ]
    return {
        "daily_budget": _bar("Daily budget usage (USD est)", rows, "label", "value"),
        "hourly_rate": _bar("Hourly call usage", rate, "label", "value"),
    }
''')

w("doofus/dashboard/live_safety_charts.py", CHART_HELPER + '''
from doofus.dashboard.live_data_api import get_rejection_reason_counts, get_safety_events

def build_safety_charts():
    return {
        "rejection_reasons": _bar("Rejection reasons", get_rejection_reason_counts(), "reason", "count"),
        "safety_events": _bar("Safety events", [{"type": e.get("event_type"), "count": 1} for e in get_safety_events()], "type", "count"),
    }
''')

w("doofus/dashboard/live_arena_charts.py", CHART_HELPER + '''
from doofus.dashboard.live_data_api import get_arena_result_matrix

def build_arena_charts():
    ar = get_arena_result_matrix()
    counts = {}
    for r in ar:
        k = r.get("arena", "unknown")
        counts[k] = counts.get(k, 0) + 1
    rows = [{"arena": k, "count": v} for k, v in counts.items()]
    return {"arena_counts": _bar("Arena result counts", rows, "arena", "count")}
''')

# B1015
w("doofus/dashboard/live_event_table.py", '''
"""Live event tables."""
from __future__ import annotations
from doofus.dashboard.live_data_api import (
    get_cycle_timeseries, get_recent_candidates, get_recent_rejections,
    get_recent_promotions, get_model_call_timeseries, get_safety_events,
)
from doofus.dashboard import live_metric_queries as mq

def build_event_tables() -> dict:
    return {
        "cycles": get_cycle_timeseries()[:30],
        "candidates": get_recent_candidates()[:30],
        "rejections": get_recent_rejections()[:30],
        "promotions": get_recent_promotions()[:30],
        "model_calls": get_model_call_timeseries()[:30],
        "safety_events": get_safety_events()[:30],
        "dashboard_events": mq.recent_dashboard_events(30),
        "heartbeats": mq.recent_heartbeats(30),
    }
''')

w("doofus/dashboard/live_report_panel.py", '''
from doofus.dashboard.live_data_api import get_latest_report_paths
from doofus.core.doofus_paths import SHARED

def build_report_panel() -> dict:
    return {"shared_folder": str(SHARED), "reports": get_latest_report_paths()}
''')

w("doofus/dashboard/live_error_panel.py", '''
from doofus.dashboard.live_state_reader import read_latest_error

def build_error_panel() -> dict:
    return {"last_error": read_latest_error() or "none"}
''')

w("doofus/dashboard/live_checkpoint_panel.py", '''
from doofus.dashboard.live_data_api import get_checkpoint_status, get_heartbeat_status

def build_checkpoint_panel() -> dict:
    return {"checkpoint": get_checkpoint_status(), "heartbeat": get_heartbeat_status()}
''')

print("bootstrap part 2 ok")
