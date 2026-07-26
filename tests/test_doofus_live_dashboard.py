"""Tests for live dashboard data API and panels."""
import pytest
from doofus.dashboard import live_data_api as api
from doofus.dashboard import live_metric_queries as mq
from doofus.dashboard.live_state_reader import read_control_state
from doofus.dashboard.live_task_reader import get_task_status
from doofus.dashboard.live_chart_models import ChartBundle, empty_line
from doofus.dashboard.live_status_panel import build_status_panel
from doofus.dashboard.live_control_panel import build_control_panel
from doofus.dashboard.live_supervisor_panel import build_supervisor_panel
from doofus.dashboard.live_model_status_panel import build_model_status_panel
from doofus.dashboard.live_safety_panel import build_safety_panel
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
from doofus.dashboard.live_event_table import build_event_tables
from doofus.dashboard.live_report_panel import build_report_panel
from doofus.dashboard.live_error_panel import build_error_panel
from doofus.dashboard.live_checkpoint_panel import build_checkpoint_panel

@pytest.fixture(autouse=True)
def _isolate_db(tmp_path, monkeypatch):
    db = tmp_path / "test.sqlite"
    monkeypatch.setattr("doofus.core.doofus_paths.METRICS_DB", db)
    monkeypatch.setattr("doofus.core.doofus_state.METRICS_DB", db)
    monkeypatch.setattr("doofus.dashboard.live_metric_queries.METRICS_DB", db)
    monkeypatch.setattr("doofus.dashboard.dashboard_data.METRICS_DB", db)
    monkeypatch.setattr("doofus.safety.budget_guard.METRICS_DB", db)
    from doofus.core.doofus_state import init_db
    init_db(db)

def test_live_data_api_snapshot():
    s = api.get_dashboard_snapshot()
    assert s["status"] == "snapshot_ok"
    assert "cards" in s
    assert s["bind"] == "127.0.0.1:8765"

def test_live_metric_queries_empty():
    assert mq.count_table("candidates") == 0
    assert mq.recent_candidates() == []

def test_live_state_reader():
    assert "may_run" in read_control_state()

def test_live_task_reader():
    t = get_task_status()
    assert "Doofus-24-7-Supervisor" in t

def test_live_chart_models():
    assert empty_line("t").title == "t"
    assert ChartBundle().classification == "DOOFUS_LIVE_CHART_BUNDLE"

def test_model_auth_no_secrets():
    a = api.get_model_auth_status()
    assert "key_present" in a
    assert a["provider_auth"] in ("no_key", "dry_run", "ok", "failing", "pending")
    assert a["provider_auth"] != "unknown"
    assert "sk-proj" not in str(a).lower()

def test_panels():
    assert "cards" in build_status_panel()
    assert build_control_panel()["writes_files_only"] is True
    assert "tasks" in build_supervisor_panel()
    assert "auth" in build_model_status_panel()
    assert "events" in build_safety_panel()

def test_charts_build():
    import plotly.graph_objects as go
    for fn in (
        build_mutation_charts, build_candidate_charts, build_lineage_charts,
        build_score_charts, build_compounding_charts, build_recursive_learning_charts,
        build_improvement_charts, build_model_charts, build_budget_charts,
        build_safety_charts, build_arena_charts,
    ):
        charts = fn()
        assert isinstance(charts, dict)
        for name, fig in charts.items():
            if hasattr(fig, "data"):
                for trace in fig.data:
                    assert not isinstance(trace, go.Bar), f"{fn.__name__}/{name} must not use bar chart"

def test_event_tables():
    assert "cycles" in build_event_tables()

def test_report_panels():
    assert "shared_folder" in build_report_panel()
    assert "last_error" in build_error_panel()
    assert "checkpoint" in build_checkpoint_panel()

def test_query_limit():
    api.set_query_limit(100)
    assert api.get_query_limit() == 100
    api.set_query_limit(500)

def test_live_dashboard_report_builder(tmp_path, monkeypatch):
    monkeypatch.setattr("doofus.reports.live_dashboard_report_builder.SHARED", tmp_path)
    from doofus.reports.live_dashboard_report_builder import export_live_dashboard_shared_folder
    r = export_live_dashboard_shared_folder()
    assert r["classification"] == "B1018_SHARED_FOLDER_LIVE_DASHBOARD_REPORT_REFRESH_PASS"
    assert (tmp_path / "DOOFUS-LIVE-DASHBOARD-FINAL-REPORT.json").exists()
