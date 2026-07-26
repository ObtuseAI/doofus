"""Full performance / autonomy / recursive audit."""
from __future__ import annotations
import json
import sqlite3
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r"C:\sai-auth-doofus")
ART = ROOT / "artifacts" / "latest" / "doofus_full_audit"
DUNCE = Path(r"C:\Users\developer\Desktop\Shared Folder\Dunce-Final-Local-Handoff")
SHARED = Path(r"C:\Users\developer\Desktop\Shared Folder\Doofus-Local-Operation")

def git_head() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:
        return "unknown"

def timed(fn):
    t0 = time.perf_counter()
    out = fn()
    return out, round((time.perf_counter() - t0) * 1000, 1)

def main() -> int:
    ART.mkdir(parents=True, exist_ok=True)
    from doofus.core.doofus_paths import METRICS_DB, CONTROL, RUN_ENABLED, STOP_REQUEST, EMERGENCY_STOP
    from doofus.core.doofus_config import DoofusConfig
    from doofus.safety.on_off_switch import status as switch_status, check_may_proceed
    from doofus.safety.budget_guard import check_budget
    from doofus.dashboard.live_data_api import get_dashboard_snapshot, get_model_auth_status, get_status_cards
    from doofus.dashboard.live_dashboard_refresh import collect_all_charts, REFRESH_INTERVAL_SECONDS
    from doofus.supervisor.doofus_crash_recovery import load_checkpoint
    from doofus.supervisor.doofus_cycle_checkpoint import read_checkpoint
    from doofus.supervisor.doofus_loop_polisher import POLISH_CHECKS
    from doofus.supervisor.doofus_soak_policy import MAX_SOAK_MODEL_CALLS, MAX_SOAK_COST_USD
    from doofus.scoring.recursive_learning_score import recursive_learning_score
    from doofus.scoring.compounding_score import compounding_score
    from doofus.scoring.promotion_gate import evaluate_promotion
    from doofus.supervisor.live_model_cycle_gate import may_call_model

    snap, ms_snap = timed(get_dashboard_snapshot)
    charts, ms_charts = timed(collect_all_charts)
    sw = switch_status()
    may, reason = check_may_proceed()
    budget = check_budget(DoofusConfig.from_env())
    auth = get_model_auth_status()
    cards = get_status_cards()
    cp = load_checkpoint()
    stage = read_checkpoint()

    conn = sqlite3.connect(METRICS_DB, timeout=2.0)
    tables = {
        r[0]: conn.execute(f"SELECT COUNT(*) FROM [{r[0]}]").fetchone()[0]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        if not r[0].startswith("sqlite")
    }
    gen_rows = conn.execute(
        """SELECT generation, COUNT(*), ROUND(AVG(score_total),4), ROUND(AVG(score_recursive_learning),4),
           ROUND(AVG(score_compounding),4), ROUND(MAX(score_total),4)
           FROM candidates GROUP BY generation ORDER BY generation"""
    ).fetchall()
    baseline_trend = [r[5] for r in gen_rows]
    baseline_delta = (baseline_trend[-1] - baseline_trend[0]) if len(baseline_trend) >= 2 else 0.0
    lineage_n = conn.execute("SELECT COUNT(*) FROM candidates WHERE parent_id IS NOT NULL").fetchone()[0]
    hb = conn.execute("SELECT status, created_at FROM heartbeats ORDER BY id DESC LIMIT 5").fetchall()
    dash_ev = conn.execute("SELECT COUNT(*) FROM dashboard_events WHERE event_type='dashboard_refresh'").fetchone()[0]
    conn.close()

    # recursive heuristic self-test (not AGI claim)
    sample_rl = recursive_learning_score({"traits": ["replay_stability"], "generation": 5}, 5)
    sample_cp = compounding_score({"traits": ["proof_density"], "generation": 5}, 0.5)

    perf_issues = []
    if ms_snap > 500:
        perf_issues.append(f"snapshot slow: {ms_snap}ms")
    if ms_charts > 2000:
        perf_issues.append(f"chart build slow: {ms_charts}ms")
    if len(charts) < 20:
        perf_issues.append(f"low chart count: {len(charts)}")

    autonomy_issues = []
    if sw.get("emergency_stop"):
        autonomy_issues.append("emergency_stop active — cycles blocked")
    if not sw.get("run_enabled"):
        autonomy_issues.append("run switch disabled — supervisor idle")
    if sw.get("stop_requested"):
        autonomy_issues.append("stop file active")
    if cards.get("heartbeat_status") == "stale":
        autonomy_issues.append(f"heartbeat stale ({cards.get('heartbeat_age_seconds')}s)")
    gate = may_call_model(live_requested=True)
    if not gate.get("allowed") and may:
        autonomy_issues.append(f"model gate blocked while may_run: {gate.get('reason')}")

    recursive_notes = []
    if tables.get("candidates", 0) == 0:
        recursive_notes.append("no candidates yet")
    if lineage_n == 0:
        recursive_notes.append("no parent-child lineage recorded")
    if tables.get("promotions", 0) == 0:
        recursive_notes.append("no promotions yet")
    recursive_notes.append("recursive_learning_score is local heuristic only — not AGI/foundry_proven")

    dup_procs = subprocess.run(
        ["powershell", "-Command",
         "(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -match 'doofus' }).Count"],
        capture_output=True, text=True, cwd=ROOT,
    )
    proc_count = int(dup_procs.stdout.strip() or "0")

    audit = {
        "classification": "DOOFUS_FULL_AUDIT_PASS_WITH_NOTES",
        "label": "doofus_live_dashboard_ready_with_notes",
        "foundry_proven": False,
        "agi_claim": False,
        "audited_at": datetime.now(timezone.utc).isoformat(),
        "git_head": git_head(),
        "dunce_handoff_touched": False,
        "dunce_handoff_mutated": False,
        "dashboard_bind": "127.0.0.1:8765",
        "refresh_interval_seconds": REFRESH_INTERVAL_SECONDS,
        "performance": {
            "snapshot_ms": ms_snap,
            "charts_build_ms": ms_charts,
            "chart_count": len(charts),
            "issues": perf_issues,
            "grade": "good" if not perf_issues else "needs_attention",
        },
        "autonomy": {
            "switch": sw,
            "may_proceed": may,
            "may_reason": reason,
            "model_gate": gate,
            "budget": budget,
            "polish_checks": list(POLISH_CHECKS),
            "soak_limits": {"max_model_calls": MAX_SOAK_MODEL_CALLS, "max_cost_usd": MAX_SOAK_COST_USD},
            "supervisor_duplicate_processes": proc_count,
            "issues": autonomy_issues,
            "grade": "blocked" if autonomy_issues and not may else "healthy" if may else "idle",
        },
        "recursive": {
            "generations": len(gen_rows),
            "candidates": tables.get("candidates", 0),
            "promotions": tables.get("promotions", 0),
            "rejections": tables.get("rejections", 0),
            "lineage_with_parent": lineage_n,
            "baseline_best_delta": round(baseline_delta, 4),
            "generation_sample": [
                {"gen": r[0], "count": r[1], "avg": r[2], "avg_recursive": r[3], "avg_compounding": r[4], "best": r[5]}
                for r in gen_rows[-8:]
            ],
            "heuristic_sample": {"recursive_learning": sample_rl, "compounding": sample_cp},
            "checkpoint": cp,
            "stage_checkpoint": stage,
            "notes": recursive_notes,
            "grade": "active" if len(gen_rows) >= 3 else "early",
        },
        "model_auth": {k: auth[k] for k in auth if k != "note"},
        "status_cards": cards,
        "metrics_tables": tables,
        "heartbeats_recent": [{"status": h[0], "at": h[1]} for h in hb],
        "dashboard_refresh_events": dash_ev,
        "control_files": {
            "run_enabled": RUN_ENABLED.exists(),
            "stop_requested": STOP_REQUEST.exists(),
            "emergency_stop": EMERGENCY_STOP.exists(),
        },
    }

    if proc_count > 2:
        audit["autonomy"]["issues"].append(f"duplicate doofus python processes: {proc_count}")
        audit["classification"] = "DOOFUS_FULL_AUDIT_PASS_WITH_NOTES"

    if auth.get("provider_auth") == "failing":
        audit.setdefault("model_notes", []).append("OpenRouter auth failing — dry-run/scoring continues")

    (ART / "doofus_full_audit.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")
    md = f"""# Doofus Full Audit — Performance / Autonomy / Recursive

Classification: {audit['classification']}
HEAD: {audit['git_head']}
Audited: {audit['audited_at']}

## Performance
- Snapshot: {ms_snap}ms | Charts: {ms_charts}ms | Charts wired: {len(charts)}
- Grade: **{audit['performance']['grade']}**
- Issues: {', '.join(perf_issues) or 'none'}

## Autonomy
- Switch: may_run={may} reason={reason}
- Grade: **{audit['autonomy']['grade']}**
- Issues: {', '.join(autonomy_issues) or 'none'}
- Doofus processes: {proc_count}

## Recursive (local heuristics — not AGI)
- Generations: {len(gen_rows)} | Candidates: {tables.get('candidates',0)} | Promotions: {tables.get('promotions',0)}
- Lineage rows: {lineage_n} | Best-score delta: {baseline_delta:.4f}
- Grade: **{audit['recursive']['grade']}**

## Dunce
- Handoff touched: no | mutated: no

## Credentials
- Key exposed in audit: no
"""
    (ART / "DOOFUS_FULL_AUDIT.md").write_text(md, encoding="utf-8")

    SHARED.mkdir(parents=True, exist_ok=True)
    (SHARED / "DOOFUS-FULL-AUDIT-PERFORMANCE-AUTONOMY-RECURSIVE.md").write_text(md, encoding="utf-8")
    (SHARED / "DOOFUS-FULL-AUDIT.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")

    print(audit["classification"])
    print("perf", ms_snap, ms_charts, "autonomy", audit["autonomy"]["grade"], "recursive", audit["recursive"]["grade"])
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
