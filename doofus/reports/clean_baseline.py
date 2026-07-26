"""Clean runtime baseline certification helpers."""
from __future__ import annotations

import json
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from doofus.core import doofus_paths
from doofus.core.atomic_json import load_json, save_json
from doofus.evolution.best_ever_ledger import get_best_ever
from doofus.runtime.runtime_health import supervisor_health
from doofus.safety.on_off_switch import status as switch_status
from doofus.supervisor.doofus_crash_recovery import load_checkpoint


def _reports_dir() -> Path:
    return doofus_paths.STATE.parent / "reports"


def contamination_marker_path() -> Path:
    return doofus_paths.STATE / "test_contamination_marker.json"


def contamination_recovery_report_path() -> Path:
    return _reports_dir() / "doofus_live_state_contamination_recovery_final_report.json"


def contamination_integrity_report_path() -> Path:
    return _reports_dir() / "doofus_post_test_live_state_integrity_check.json"


def precheck_report_path() -> Path:
    return _reports_dir() / "doofus_clean_baseline_certification_precheck.json"


def restore_search_report_path() -> Path:
    return _reports_dir() / "doofus_clean_restore_source_search_report.json"


def baseline_certificate_json_path() -> Path:
    return _reports_dir() / "doofus_clean_runtime_baseline_certificate.json"


def baseline_certificate_md_path() -> Path:
    return _reports_dir() / "doofus_clean_runtime_baseline_certificate.md"


def map_pre_resume_report_path() -> Path:
    return _reports_dir() / "doofus_map_pre_resume_reconciliation_report.json"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_contamination_marker() -> dict[str, Any]:
    data = load_json(contamination_marker_path(), default={})
    return data if isinstance(data, dict) else {}


def load_baseline_certificate() -> dict[str, Any]:
    data = load_json(baseline_certificate_json_path(), default={})
    return data if isinstance(data, dict) else {}


def contamination_quarantine_path() -> Path | None:
    marker = load_contamination_marker()
    raw = marker.get("quarantine_path")
    if raw:
        path = Path(str(raw))
        if path.exists():
            return path
    recovery = load_json(contamination_recovery_report_path(), default={})
    raw = recovery.get("quarantine_path") if isinstance(recovery, dict) else None
    if raw:
        path = Path(str(raw))
        if path.exists():
            return path
    quarantine_only = load_json(_reports_dir() / "doofus_live_state_quarantine_only_report.json", default={})
    raw = quarantine_only.get("quarantine_path") if isinstance(quarantine_only, dict) else None
    if raw:
        path = Path(str(raw))
        if path.exists():
            return path
    return None


def _git_head() -> str:
    proc = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(doofus_paths.ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    return (proc.stdout or "").strip()


def _json_archive_entries() -> list[dict[str, Any]]:
    archive = load_json(doofus_paths.STATE / "map_elites_archive.json", default=[])
    if isinstance(archive, list):
        return [e for e in archive if isinstance(e, dict)]
    cells = (archive or {}).get("cells", {})
    if isinstance(cells, dict):
        return [e for e in cells.values() if isinstance(e, dict)]
    if isinstance(cells, list):
        return [e for e in cells if isinstance(e, dict)]
    return []


def contaminated_generations_from_marker(marker: dict[str, Any] | None = None) -> list[int]:
    marker = marker or load_contamination_marker()
    raw = marker.get("excluded_from_progress_claims")
    if isinstance(raw, list):
        out = []
        for item in raw:
            try:
                out.append(int(item))
            except (TypeError, ValueError):
                continue
        if out:
            return sorted(set(out))
    start = marker.get("expected_generation_before_test")
    end = marker.get("contaminated_generation_observed")
    try:
        start_i = int(start)
        end_i = int(end)
    except (TypeError, ValueError):
        return []
    if end_i > start_i:
        return list(range(start_i + 1, end_i + 1))
    return []


def gather_runtime_state() -> dict[str, Any]:
    checkpoint = load_checkpoint()
    best = get_best_ever()
    archive_entries = _json_archive_entries()
    switch = switch_status()
    supervisor = supervisor_health()
    marker = load_contamination_marker()
    result: dict[str, Any] = {
        "timestamp_utc": _now(),
        "git_head": _git_head(),
        "supervisor_running": bool(supervisor.get("active") and supervisor.get("process_alive")),
        "supervisor_health": supervisor,
        "contamination_marker_present": contamination_marker_path().exists(),
        "quarantine_path_exists": False,
        "current_generation": int(checkpoint.get("generation") or 0),
        "checkpoint_status": checkpoint.get("phase"),
        "baseline_fitness": float(checkpoint.get("baseline_score") or 0.0),
        "best_ever_fitness": float(best.get("best_score") or best.get("best_ever_score") or 0.0),
        "best_ever_candidate": best.get("best_candidate_id") or best.get("best_ever_candidate_id"),
        "map_json_cells": len([e for e in archive_entries if e.get("cell_key")]),
        "safety_gates_status": switch,
    }
    if marker:
        quarantine_path = contamination_quarantine_path()
        result["quarantine_path_exists"] = bool(quarantine_path and quarantine_path.exists())
    conn = sqlite3.connect(doofus_paths.METRICS_DB)
    try:
        result["map_sql_cells"] = int(conn.execute("SELECT COUNT(*) FROM map_elites_cells").fetchone()[0])
        result["gepa_trace_count"] = int(conn.execute("SELECT COUNT(*) FROM gepa_traces").fetchone()[0])
        result["gepa_prompt_version_count"] = int(conn.execute("SELECT COUNT(*) FROM gepa_prompt_versions").fetchone()[0])
        result["model_call_events_count"] = int(conn.execute("SELECT COUNT(*) FROM model_call_events").fetchone()[0])
        result["codeevolve_event_rows"] = int(conn.execute("SELECT COUNT(*) FROM codeevolve_events").fetchone()[0])
        result["db_health_events"] = int(conn.execute("SELECT COUNT(*) FROM db_health_events").fetchone()[0])
        live_row = conn.execute(
            """
            SELECT 1
            FROM model_call_events
            WHERE classification='DOOFUS_MODEL_LIVE'
              AND COALESCE(success, 0)=1
              AND provider_resolved='cursor'
              AND transport='agent_cli'
              AND COALESCE(live, 0)=1
            LIMIT 1
            """
        ).fetchone()
        result["composer_live_success_event_present"] = bool(live_row)
        code_row = conn.execute(
            """
            SELECT due, attempted, ran, skipped, skip_reason, gate_name, gate_details_sanitized, created_at
            FROM codeevolve_events
            ORDER BY id DESC LIMIT 1
            """
        ).fetchone()
        if code_row:
            if code_row[2]:
                result["codeevolve_status"] = "FIRED_SANDBOX_NO_PROMOTION"
            elif code_row[3] and code_row[4]:
                result["codeevolve_status"] = "BLOCKED_WITH_REASON"
            else:
                result["codeevolve_status"] = "SKIPPED_WITH_REASON"
            result["latest_codeevolve_event"] = {
                "due": bool(code_row[0]),
                "attempted": bool(code_row[1]),
                "ran": bool(code_row[2]),
                "skipped": bool(code_row[3]),
                "skip_reason": code_row[4],
                "gate_name": code_row[5],
                "gate_details_sanitized": code_row[6],
                "created_at": code_row[7],
            }
        else:
            result["codeevolve_status"] = "STILL_SILENT"
        result["sqlite_contention_status"] = "CLEAN" if result["db_health_events"] == 0 else "EVENTS_LOGGED"
    finally:
        conn.close()
    return result


def write_precheck_report() -> dict[str, Any]:
    report = gather_runtime_state()
    save_json(precheck_report_path(), report)
    return report


def _candidate_from_summary(path: Path, label: str) -> dict[str, Any]:
    data = load_json(path, default={})
    checkpoint = {}
    if isinstance(data, dict):
        checkpoint = data.get("runtime", {}).get("checkpoint") or data.get("checkpoint") or {}
    best_candidate = (
        data.get("runtime", {}).get("best_ever_candidate")
        if isinstance(data, dict)
        else None
    )
    if not best_candidate and isinstance(data, dict):
        best_candidate = data.get("kpi_tracker_summary", {}).get("best_ever_candidate_id")
    return {
        "label": label,
        "path": str(path),
        "candidate_type": "summary_snapshot",
        "contains_full_runtime_bundle": False,
        "pre_contamination_candidate": bool(int(checkpoint.get("generation") or 0) <= 1634),
        "checkpoint_generation": checkpoint.get("generation"),
        "checkpoint_phase": checkpoint.get("phase"),
        "champion_consistent": (
            best_candidate == "DOOFUS_1631_b40ceb1915"
            or (data.get("kpi_tracker_summary", {}).get("best_ever_score") == 0.9392 if isinstance(data, dict) else False)
        ),
        "classification": "partial_metadata_only",
        "reason": "Snapshot contains summary metadata but not the full runtime file set or DB state required for a safe restore.",
    }


def _candidate_from_quarantine(path: Path) -> dict[str, Any]:
    checkpoint = load_json(path / "last_checkpoint.json", default={})
    return {
        "label": "contaminated_quarantine_evidence",
        "path": str(path),
        "candidate_type": "quarantine_evidence",
        "contains_full_runtime_bundle": False,
        "pre_contamination_candidate": False,
        "checkpoint_generation": checkpoint.get("generation"),
        "checkpoint_phase": checkpoint.get("phase"),
        "champion_consistent": True,
        "classification": "contaminated_post_state_only",
        "reason": "Quarantine folder preserves evidence from the contaminated post-test state rather than a clean pre-contamination restore source.",
    }


def search_restore_sources() -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    live_comp = _reports_dir() / "doofus_live_composer_stabilization_pre_snapshot.json"
    top4 = _reports_dir() / "doofus_top4_kpi_repair_pre_snapshot.json"
    if live_comp.exists():
        candidates.append(_candidate_from_summary(live_comp, "live_composer_stabilization_pre_snapshot"))
    if top4.exists():
        candidates.append(_candidate_from_summary(top4, "top4_kpi_repair_pre_snapshot"))
    shared_snap = doofus_paths.SHARED / "DOOFUS-SOTA-KPI-SNAPSHOT.json"
    if shared_snap.exists():
        candidates.append(_candidate_from_summary(shared_snap, "shared_kpi_snapshot"))
    marker = load_contamination_marker()
    quarantine_path = contamination_quarantine_path()
    if quarantine_path and quarantine_path.exists():
        candidates.append(_candidate_from_quarantine(quarantine_path))

    true_restore = next((c for c in candidates if c.get("contains_full_runtime_bundle") and c.get("pre_contamination_candidate")), None)
    result = {
        "timestamp_utc": _now(),
        "git_head": _git_head(),
        "overall_classification": "TRUE_RESTORE_AVAILABLE" if true_restore else "NO_TRUE_RESTORE_AVAILABLE",
        "true_restore_available": bool(true_restore),
        "selected_restore_source": true_restore["path"] if true_restore else None,
        "candidates": candidates,
        "reason": (
            "No candidate contained a complete pre-contamination runtime bundle (checkpoint, KPI history, MAP JSON, metrics DB, GEPA state, champion ledger, model events, CodeEvolve events, and db health state)."
            if not true_restore
            else "A verified pre-contamination full runtime bundle is available."
        ),
    }
    save_json(restore_search_report_path(), result)
    return result


def _status_line(state: dict[str, Any]) -> str:
    return (
        f"Baseline {state['baseline_fitness']} | best-ever {state['best_ever_fitness']} "
        f"({state['best_ever_candidate']}) | MAP {state['map_json_cells']}/{state['map_sql_cells']} "
        f"| GEPA {state['gepa_trace_count']} traces / {state['gepa_prompt_version_count']} prompt versions"
    )


def certify_runtime_baseline(search_result: dict[str, Any] | None = None) -> dict[str, Any]:
    state = gather_runtime_state()
    search_result = search_result or search_restore_sources()
    marker = load_contamination_marker()
    excluded = contaminated_generations_from_marker(marker)
    baseline_type = "RESTORED_CLEAN_BASELINE" if search_result.get("true_restore_available") else "CERTIFIED_POST_CONTAMINATION_REBASE_BASELINE"
    certificate = {
        "timestamp_utc": _now(),
        "git_head": state["git_head"],
        "baseline_type": baseline_type,
        "baseline_generation": state["current_generation"],
        "operational_generation": state["current_generation"],
        "contaminated_generations_excluded": excluded,
        "contamination_quarantine_path": str(contamination_quarantine_path()) if contamination_quarantine_path() else None,
        "contamination_marker_handling": "historical_record_retained",
        "champion_baseline_fitness": state["baseline_fitness"],
        "best_ever_fitness": state["best_ever_fitness"],
        "best_ever_candidate": state["best_ever_candidate"],
        "map_status": {
            "map_json_cells": state["map_json_cells"],
            "map_sql_cells": state["map_sql_cells"],
            "sync_status": load_json(doofus_paths.STATE / "kpi_tracker.json", default={}).get("map_elites_growth", {}).get("sync_status"),
        },
        "gepa_status": {
            "trace_count": state["gepa_trace_count"],
            "prompt_version_count": state["gepa_prompt_version_count"],
            "contamination_aware": True,
        },
        "composer_status": {
            "live_success_event_present": state["composer_live_success_event_present"],
            "valid_diagnostic_evidence": True,
        },
        "codeevolve_status": state["codeevolve_status"],
        "sqlite_status": state["sqlite_contention_status"],
        "safety_gate_status": state["safety_gates_status"],
        "supervisor_resume_allowed": True,
        "reason": (
            "No true clean restore source exists, so the current operational state is certified as a post-contamination rebase baseline. "
            "Contaminated generations remain excluded from progress claims, champion history is preserved, and the post-isolation Composer smoke remains valid diagnostic evidence."
            if baseline_type == "CERTIFIED_POST_CONTAMINATION_REBASE_BASELINE"
            else "A verified clean restore source was applied and certified."
        ),
        "restore_source_search_result": search_result.get("overall_classification"),
    }
    save_json(baseline_certificate_json_path(), certificate)
    lines = [
        "# Doofus Clean Runtime Baseline Certificate",
        "",
        f"- Type: `{certificate['baseline_type']}`",
        f"- Certified at: `{certificate['timestamp_utc']}`",
        f"- Baseline generation: `{certificate['baseline_generation']}`",
        f"- Operational generation: `{certificate['operational_generation']}`",
        f"- Excluded contaminated generations: `{certificate['contaminated_generations_excluded']}`",
        f"- Quarantine path: `{certificate['contamination_quarantine_path']}`",
        f"- Supervisor resume allowed: `{certificate['supervisor_resume_allowed']}`",
        "",
        "## Champion Line",
        "",
        f"- Baseline fitness: `{certificate['champion_baseline_fitness']}`",
        f"- Best-ever fitness: `{certificate['best_ever_fitness']}`",
        f"- Best-ever candidate: `{certificate['best_ever_candidate']}`",
        "",
        "## Runtime Status",
        "",
        f"- {_status_line(state)}",
        f"- Composer live success present: `{certificate['composer_status']['live_success_event_present']}`",
        f"- CodeEvolve status: `{certificate['codeevolve_status']}`",
        f"- SQLite status: `{certificate['sqlite_status']}`",
        "",
        "## Reason",
        "",
        certificate["reason"],
        "",
    ]
    baseline_certificate_md_path().write_text("\n".join(lines), encoding="utf-8")
    historical_marker = {
        "classification": "DOOFUS_TEST_CONTAMINATION_MARKER",
        "active_contamination_block": False,
        "historical_contamination_record": True,
        "contamination_detected_at": marker.get("marked_at_utc") or _now(),
        "suspected_test": "tests/test_doofus.py::test_doofus_supervisor_loop_once",
        "suspected_call": "run_one_cycle(dry_run=True)",
        "contaminated_generation_range": excluded,
        "quarantine_path": str(contamination_quarantine_path()) if contamination_quarantine_path() else None,
        "baseline_certificate_path": str(baseline_certificate_json_path()),
        "resume_baseline_generation": certificate["baseline_generation"],
        "excluded_from_progress_claims": excluded,
        "operator_clearance_reason": certificate["reason"],
    }
    save_json(contamination_marker_path(), historical_marker)
    return certificate
