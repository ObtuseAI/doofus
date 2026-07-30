"""Doofus live NiceGUI dashboard — 127.0.0.1 only, 30s unified refresh."""
from __future__ import annotations
import json
import subprocess
import threading
from datetime import datetime, timezone
from nicegui import ui
from doofus.core.doofus_config import DoofusConfig
from doofus.core.doofus_paths import ROOT, SHARED, STATE
from doofus.dashboard.live_data_api import (
    get_dashboard_snapshot,
    get_status_cards,
    get_model_auth_status,
    get_budget_rate_status,
    get_task_status,
    set_query_limit,
    get_query_limit,
    _git_head,
)
from doofus.dashboard.live_dashboard_refresh import (
    REFRESH_INTERVAL_SECONDS,
    collect_all_charts,
    record_dashboard_refresh,
)
from doofus.dashboard.live_event_table import build_event_tables
from doofus.dashboard.live_checkpoint_panel import build_checkpoint_panel
from doofus.dashboard.agora_panel import build_agora_panel
from doofus.safety.on_off_switch import start, stop, emergency_stop, clear_emergency
from doofus.dashboard.dashboard_health import dashboard_reachable
from doofus.supervisor.process_singleton import (
    acquire_singleton,
    cleanup_stale_lock,
    clear_lock_unless_pid_listening,
    read_singleton_pid,
    release_singleton,
    _pid_alive,
)
from doofus.dashboard.live_dashboard_refresh import invalidate_chart_cache

cfg = DoofusConfig.from_env()
PYTHON = str(ROOT / ".venv_doofus" / "Scripts" / "python.exe")

_chart_registry: dict = {}
_tab_columns: dict = {}
_label_refs: dict = {}
_table_refs: dict = {}
_json_refs: dict = {}
_last_refresh_label = None
_charts_lock = threading.Lock()
_charts_loading = False
_charts_error: str | None = None
_chart_status_label = None
_pending_built_charts: dict | None = None
_diag_lock = threading.Lock()
_pending_diagnostics: dict | None = None
_diagnostics_loading = False
_status_lock = threading.Lock()
_pending_status: dict | None = None
_status_loading = False
STATUS_CACHE = STATE / "dashboard_status_cache.json"


def _load_status_cache() -> dict | None:
    try:
        if STATUS_CACHE.exists():
            return json.loads(STATUS_CACHE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return None


def _save_status_cache(payload: dict) -> None:
    try:
        STATE.mkdir(parents=True, exist_ok=True)
        STATUS_CACHE.write_text(json.dumps(payload, default=str), encoding="utf-8")
    except Exception:
        pass


def _bootstrap_status_ui() -> None:
    """Instant status from files/cache — no SQLite (never blocks page render)."""
    cached = _load_status_cache()
    if cached and cached.get("c"):
        _apply_status(cached)
        return
    from doofus.safety.on_off_switch import status as switch_status
    from doofus.supervisor.doofus_crash_recovery import load_checkpoint

    sw = switch_status()
    cp = load_checkpoint()
    gen = cp.get("generation", "?")
    may = "YES" if sw.get("may_run") else "NO"
    emerg = "YES" if sw.get("emergency_stop") else "NO"
    op = "RUNNING" if sw.get("may_run") else "IDLE"
    line = (
        f"{op} | may_run: {may} | emergency: {emerg} | "
        f"Gen: {gen} | Cand: … | Prom: … | Rej: … | HB: … | (live metrics loading)"
    )
    if _label_refs.get("status"):
        _label_refs["status"].set_text(line)


def _apply_status(payload: dict, *, notify: bool = False) -> None:
    if payload.get("error"):
        if _label_refs.get("status"):
            exc = payload["error"]
            _label_refs["status"].set_text(f"Status error: {type(exc).__name__}: {exc}")
        return
    c = payload["c"]
    auth = payload["auth"]
    budget = payload["budget"]
    tasks = payload["tasks"]
    if _label_refs.get("status"):
        _label_refs["status"].set_text(_format_status_line(c))
    if _label_refs.get("detail"):
        _label_refs["detail"].set_text(_format_detail_line(c, auth, budget, tasks))
    if _label_refs.get("auth"):
        _label_refs["auth"].set_text(
            f"Key: {'YES' if auth.get('key_present') else 'NO'} | "
            f"Provider auth: {auth.get('provider_auth')} | {auth.get('auth_summary', '')}"
        )
    if _last_refresh_label:
        _last_refresh_label.set_text(
            f"Last refresh: {datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC "
            f"(status every {REFRESH_INTERVAL_SECONDS}s, charts async)"
        )
    if _json_refs.get("tasks"):
        try:
            _json_refs["tasks"].props["content"] = {"mode": "tree", "json": tasks}
        except Exception:
            pass
    if notify:
        ui.notify("Status refreshed", type="positive")
    _save_status_cache(payload)


def _status_worker() -> None:
    global _pending_status, _status_loading
    try:
        payload = {
            "c": get_status_cards(fast=True),
            "auth": get_model_auth_status(fast=True),
            "budget": get_budget_rate_status(),
            "tasks": get_task_status(),
        }
        with _status_lock:
            _pending_status = payload
    except Exception as exc:
        with _status_lock:
            _pending_status = {"error": exc}
    finally:
        _status_loading = False


def _start_status_load() -> None:
    global _status_loading
    with _status_lock:
        if _status_loading:
            return
        _status_loading = True
    threading.Thread(target=_status_worker, daemon=True).start()


def _poll_pending_status(*, notify: bool = False) -> None:
    global _pending_status
    with _status_lock:
        payload = _pending_status
        _pending_status = None
    if payload:
        _apply_status(payload, notify=notify)


def refresh_status(*, notify: bool = False) -> None:
    """Kick off async status load — never block the NiceGUI event loop."""
    _start_status_load()
    if notify:
        ui.timer(0.5, lambda: _poll_pending_status(notify=True), once=True)


_CHART_TAB_BY_PREFIX = {
    "score": "Overview",
    "mutation": "Live charts",
    "compounding": "Live charts",
    "recursive": "Live charts",
    "candidate": "Candidates",
    "lineage": "Candidates",
    "improvement": "Improvements",
    "model": "Model & cost",
    "budget": "Model & cost",
    "safety": "Safety",
    "arena": "Arenas",
    "map": "Meta Evolution",
    "gepa": "Meta Evolution",
    "gep": "Meta Evolution",
    "metacognition": "Metacognition",
}


def _mount_charts_from_dict(charts: dict) -> int:
    mounted = 0
    for key, fig in charts.items():
        if not hasattr(fig, "update_layout"):
            continue
        if key in _chart_registry:
            _chart_registry[key].update_figure(fig)
            mounted += 1
            continue
        prefix = key.split(".", 1)[0]
        tab = _CHART_TAB_BY_PREFIX.get(prefix)
        col = _tab_columns.get(tab or "")
        if col is None:
            continue
        with col:
            _chart_registry[key] = ui.plotly(fig).classes("w-full")
        mounted += 1
    return mounted


def _charts_build_worker(*, force: bool = False) -> None:
    global _pending_built_charts, _charts_loading, _charts_error
    try:
        _pending_built_charts = collect_all_charts(force=force)
        _charts_error = None
    except Exception as exc:
        _charts_error = str(exc)
    finally:
        _charts_loading = False


def _start_charts_build(*, force: bool = False) -> None:
    global _charts_loading
    with _charts_lock:
        if _charts_loading:
            return
        _charts_loading = True
    threading.Thread(target=_charts_build_worker, kwargs={"force": force}, daemon=True).start()


def _poll_mount_charts() -> None:
    global _pending_built_charts
    if _pending_built_charts is None:
        return
    charts = _pending_built_charts
    _pending_built_charts = None
    _charts_ready_from_dict(charts)


def _charts_ready_from_dict(charts: dict, *, notify: bool = False) -> None:
    global _charts_error
    try:
        n = _mount_charts_from_dict(charts)
        tables = build_event_tables()
        if "candidates" in _table_refs and tables.get("candidates"):
            safe = [{k: str(v)[:120] for k, v in r.items()} for r in tables["candidates"][:30]]
            _table_refs["candidates"].rows = safe
            _table_refs["candidates"].update()
        if "safety_events" in _table_refs and tables.get("safety_events"):
            safe = [{k: str(v)[:120] for k, v in r.items()} for r in tables["safety_events"][:30]]
            _table_refs["safety_events"].rows = safe
            _table_refs["safety_events"].update()
        if _chart_status_label is not None:
            _chart_status_label.set_text(
                f"Charts loaded: {n} series (auto-refresh {REFRESH_INTERVAL_SECONDS}s)"
            )
        record_dashboard_refresh("charts_mount")
        if notify:
            ui.notify("Charts refreshed", type="positive")
    except Exception as exc:
        _charts_error = str(exc)
        if _chart_status_label is not None:
            _chart_status_label.set_text(f"Chart error: {_charts_error}")


def refresh_all(*, notify: bool = False) -> None:
    """Status immediately; charts build in background then mount on UI thread."""
    refresh_status(notify=notify)
    invalidate_chart_cache()
    _start_charts_build(force=True)
    if notify:
        ui.timer(1.0, lambda: _poll_mount_charts(), once=True)


def _run_subprocess(args: list[str]) -> None:
    subprocess.Popen(
        args,
        cwd=str(ROOT),
        creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
    )
    ui.notify("Command started locally", type="info")

def _format_status_line(c: dict) -> str:
    hb = c.get("heartbeat_age_seconds")
    hb_s = f"{hb:.0f}s ({c.get('heartbeat_status', '?')})" if hb is not None else "none"
    return (
        f"{c.get('operation_state')} | may_run: {'YES' if c.get('may_run') else 'NO'} | "
        f"emergency: {'YES' if c.get('emergency_stop_active') else 'NO'} | "
        f"Gen: {c.get('current_generation')} | Cand: {c.get('total_candidates')} | "
        f"Prom: {c.get('total_promoted')} | Rej: {c.get('total_rejected')} | "
        f"HB: {hb_s} | Model: {c.get('model_mode')} | Auth: {c.get('model_auth_status')}"
    )

def _format_detail_line(c: dict, auth: dict, budget: dict, tasks: dict) -> str:
    return (
        f"Key: {'YES' if auth.get('key_present') else 'NO'} | Auth: {auth.get('provider_auth')} — {auth.get('auth_summary', '')} | "
        f"Cost/day: ${budget.get('daily_cost_est', 0):.4f} (remaining ${budget.get('budget_remaining_usd', 0):.2f}) | "
        f"Calls/hr: {budget.get('calls_last_hour', 0)}/{budget.get('max_calls_per_hour', 60)} | "
        f"Supervisor: {tasks.get('Doofus-24-7-Supervisor', {}).get('state', 'not registered')} | "
        f"Dashboard: {tasks.get('Doofus-Local-Dashboard', {}).get('state', 'not registered')}"
    )

def _tab_chart_column(tab: str) -> None:
    _tab_columns[tab] = ui.column().classes("w-full chart-area")

def _confirm_clear_emergency() -> None:
    with ui.dialog() as dlg, ui.card():
        ui.label("Clear emergency stop? Then click Start to resume.")
        with ui.row():
            ui.button("Cancel", on_click=dlg.close)
            ui.button("Clear", on_click=lambda: (clear_emergency(), dlg.close(), refresh_all(), ui.notify("Emergency cleared")))
    dlg.open()


def _acquire_dashboard_singleton() -> bool:
    """Take lock; ignore cross-port zombies (e.g. unkillable PID 9572 on 8765)."""
    port = cfg.dashboard_port
    cleanup_stale_lock("doofus_dashboard")
    clear_lock_unless_pid_listening("doofus_dashboard", port)
    pid = read_singleton_pid("doofus_dashboard")
    if pid and _pid_alive(pid):
        if dashboard_reachable(port=port, timeout=1.5):
            return False
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
        cleanup_stale_lock("doofus_dashboard")
        clear_lock_unless_pid_listening("doofus_dashboard", port)
    return acquire_singleton("doofus_dashboard")


def _diagnostics_worker() -> None:
    global _pending_diagnostics, _diagnostics_loading
    try:
        snap = get_dashboard_snapshot(fast=True)
        cp = build_checkpoint_panel()
        with _diag_lock:
            _pending_diagnostics = {"snapshot": snap, "checkpoint": cp}
    except Exception as exc:
        with _diag_lock:
            _pending_diagnostics = {"snapshot": {"error": type(exc).__name__}, "checkpoint": {}}
    finally:
        _diagnostics_loading = False


def _start_diagnostics_load() -> None:
    global _diagnostics_loading
    with _diag_lock:
        if _diagnostics_loading:
            return
        _diagnostics_loading = True
    threading.Thread(target=_diagnostics_worker, daemon=True).start()


def _poll_pending_diagnostics() -> None:
    global _pending_diagnostics
    with _diag_lock:
        payload = _pending_diagnostics
        _pending_diagnostics = None
    if not payload:
        return
    try:
        if _json_refs.get("diagnostics"):
            _json_refs["diagnostics"].props["content"] = {
                "mode": "tree",
                "json": payload.get("snapshot", {}),
            }
        if _json_refs.get("checkpoint"):
            _json_refs["checkpoint"].props["content"] = {
                "mode": "tree",
                "json": payload.get("checkpoint", {}),
            }
        if _json_refs.get("meta_evolution"):
            _json_refs["meta_evolution"].props["content"] = {
                "mode": "tree",
                "json": payload.get("snapshot", {}).get("meta_evolution", {}),
            }
        if _json_refs.get("metacognition"):
            _json_refs["metacognition"].props["content"] = {
                "mode": "tree",
                "json": payload.get("snapshot", {}).get("metacognition", {}),
            }
    except Exception:
        pass


def main() -> None:
    global _last_refresh_label
    if not _acquire_dashboard_singleton():
        print("Doofus dashboard already running — exiting duplicate instance")
        return

    @ui.page("/")
    def dashboard_page() -> None:
        global _last_refresh_label, _chart_status_label, _pending_built_charts
        _chart_registry.clear()
        _tab_columns.clear()
        _label_refs.clear()
        _table_refs.clear()
        _json_refs.clear()
        _pending_built_charts = None
        ui.dark_mode().enable()
        ui.query("body").classes("doofus-dash")
        ui.add_css("""
            body.doofus-dash, body.doofus-dash .nicegui-content {
                background: #0f1218 !important;
                min-height: 100vh;
            }
            .doofus-dash .q-tab-panel { background: transparent; }
            .doofus-dash .q-card { background: #1a2030; border: 1px solid #2a3140; }
            .doofus-dash-header { color: #e2e8f0; letter-spacing: 0.02em; }
            .doofus-dash-muted { color: #8896a8; }
            .doofus-dash .chart-area { width: 100%; }
            .doofus-dash .chart-area .js-plotly-plot {
                min-height: 420px;
                margin-bottom: 16px;
                border: 1px solid #2a3140;
                border-radius: 8px;
                padding: 4px;
                background: #141820;
            }
        """)

        try:
            head = _git_head()
        except Exception:
            head = "unknown"
        snap = {"cards": {"git_head": head}}

        ui.label("Doofus Evolution Dashboard").classes("text-h4 doofus-dash-header q-px-md q-pt-md")
        ui.label(
            f"127.0.0.1:{cfg.dashboard_port} | HEAD {head} | Auto-refresh {REFRESH_INTERVAL_SECONDS}s | "
            "Evidence-gated optimization | Local-first control plane"
        ).classes("text-caption doofus-dash-muted q-px-md")

        _label_refs["status"] = ui.label("Loading status...").classes("q-px-md text-white")
        _label_refs["detail"] = ui.label("").classes("q-px-md text-grey-4")
        _last_refresh_label = ui.label("").classes("q-px-md text-grey-5")
        _bootstrap_status_ui()

        with ui.row().classes("gap-2 flex-wrap q-px-md"):
            ui.button("Start", on_click=lambda: (start(), refresh_all(notify=True)))
            ui.button("Stop", on_click=lambda: (stop(), refresh_all(notify=True)))
            ui.button("Emergency Stop", on_click=lambda: (emergency_stop(), refresh_all(notify=True)))
            ui.button("Clear Emergency", on_click=_confirm_clear_emergency)
            ui.button("Dry Cycle", on_click=lambda: _run_subprocess([PYTHON, "-m", "doofus.supervisor.doofus_loop_runner", "--once", "--dry-run"]))
            ui.button("Live Cycle", on_click=lambda: _run_subprocess([PYTHON, "-m", "doofus.supervisor.doofus_loop_runner", "--once", "--live-model-if-available"]))
            ui.button("Refresh Now", on_click=lambda: refresh_all(notify=True))

        ui.label(f"Evidence workspace: {SHARED}").classes("text-caption doofus-dash-muted q-px-md")

        def on_limit(e):
            set_query_limit(int(e.value))
            refresh_all()

        ui.select([100, 200, 500, 1000], value=get_query_limit(), label="Chart history limit", on_change=on_limit).classes("w-40 q-px-md")

        with ui.tabs().classes("w-full q-px-md") as tabs:
            ui.tab("Overview")
            ui.tab("Control")
            ui.tab("Live charts")
            ui.tab("Candidates")
            ui.tab("Improvements")
            ui.tab("Model & cost")
            ui.tab("Safety")
            ui.tab("Arenas")
            ui.tab("Meta Evolution")
            ui.tab("Metacognition")
            ui.tab("Tasks")
            ui.tab("Reports")
            ui.tab("Agora")
            ui.tab("Diagnostics")

        with ui.tab_panels(tabs, value="Overview").classes("w-full q-px-md"):
            with ui.tab_panel("Overview"):
                global _chart_status_label
                ui.label("Score trends").classes("text-subtitle1")
                _chart_status_label = ui.label("Loading charts...").classes("text-caption doofus-dash-muted")
                _tab_chart_column("Overview")

            with ui.tab_panel("Control"):
                ui.label("Switch files only — no safety bypass").classes("text-caption doofus-dash-muted")
                ui.label("Start → writes DOOFUS_RUN.enabled | Stop → DOOFUS_STOP.request | Emergency → DOOFUS_EMERGENCY_STOP.request")

            with ui.tab_panel("Live charts"):
                ui.label("Mutation, compounding, and recursive learning").classes("text-caption doofus-dash-muted")
                _tab_chart_column("Live charts")

            with ui.tab_panel("Candidates"):
                _tab_chart_column("Candidates")
                t = ui.table(
                    columns=[
                        {"name": "candidate_id", "label": "ID", "field": "candidate_id"},
                        {"name": "generation", "label": "Gen", "field": "generation"},
                        {"name": "score_total", "label": "Score", "field": "score_total"},
                        {"name": "status", "label": "Status", "field": "status"},
                    ],
                    rows=[],
                ).classes("w-full")
                _table_refs["candidates"] = t

            with ui.tab_panel("Improvements"):
                _tab_chart_column("Improvements")

            with ui.tab_panel("Model & cost"):
                _label_refs["auth"] = ui.label("")
                _tab_chart_column("Model & cost")

            with ui.tab_panel("Safety"):
                st = ui.table(
                    columns=[
                        {"name": "event_type", "label": "Type", "field": "event_type"},
                        {"name": "detail", "label": "Detail", "field": "detail"},
                        {"name": "created_at", "label": "At", "field": "created_at"},
                    ],
                    rows=[],
                ).classes("w-full")
                _table_refs["safety_events"] = st
                _tab_chart_column("Safety")

            with ui.tab_panel("Arenas"):
                _tab_chart_column("Arenas")

            with ui.tab_panel("Meta Evolution"):
                ui.label("MAP-Elites, GEPA, GEP, A-Evolve, CodeEvolve").classes("text-caption doofus-dash-muted")
                _json_refs["meta_evolution"] = ui.json_editor({"content": {"mode": "tree", "json": snap.get("meta_evolution", {})}}).classes("w-full")
                _tab_chart_column("Meta Evolution")

            with ui.tab_panel("Metacognition"):
                ui.label("Experimental calibrated monitoring, bounded control, and research gates").classes("text-caption doofus-dash-muted")
                _json_refs["metacognition"] = ui.json_editor({"content": {"mode": "tree", "json": snap.get("metacognition", {})}}).classes("w-full")
                _tab_chart_column("Metacognition")

            with ui.tab_panel("Tasks"):
                _json_refs["tasks"] = ui.json_editor({"content": {"mode": "tree", "json": {}}}).classes("w-full")
                _json_refs["checkpoint"] = ui.json_editor({"content": {"mode": "tree", "json": {}}}).classes("w-full")

            with ui.tab_panel("Reports"):
                ui.label(f"Shared: {SHARED}").classes("text-caption doofus-dash-muted")
                ui.label("Report list loads after dashboard binds (auto-refresh).").classes("text-caption doofus-dash-muted")

            with ui.tab_panel("Agora"):
                build_agora_panel()

            with ui.tab_panel("Diagnostics"):
                _json_refs["diagnostics"] = ui.json_editor({"content": {"mode": "tree", "json": snap}}).classes("w-full")

        ui.label("Localhost-only | explicit control files | secrets never rendered").classes("text-caption doofus-dash-muted q-mt-md q-px-md q-pb-md")

        ui.timer(float(REFRESH_INTERVAL_SECONDS), refresh_status)
        ui.timer(0.05, refresh_status, once=True)
        ui.timer(0.5, _poll_pending_status)

        def _charts_ready_page() -> None:
            _start_charts_build(force=True)

        ui.timer(0.2, _charts_ready_page, once=True)
        ui.timer(1.0, _poll_mount_charts)
        ui.timer(45.0, lambda: _start_charts_build(force=False))
        ui.timer(3.0, _start_diagnostics_load, once=True)
        ui.timer(2.0, _poll_pending_diagnostics)

    assert cfg.dashboard_host == "127.0.0.1", "Dashboard must bind localhost only"
    ui.run(host=cfg.dashboard_host, port=cfg.dashboard_port, reload=False, show=False)

if __name__ in {"__main__", "__mp_main__"}:
    main()
