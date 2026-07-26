# -*- coding: utf-8 -*-
"""SOTA KPI tracker - Composer, fallback, cost, replay, champion, meta cadence, SQLite."""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from doofus.core.atomic_json import load_json, save_json
from doofus.core.doofus_paths import METRICS_DB as METRICS_DB
from doofus.core.doofus_paths import SHARED, STATE
from doofus.core.doofus_state import init_db
from doofus.core.metrics_db import connect_metrics_db
from doofus.evolution.best_ever_ledger import get_best_ever
from doofus.meta.recursive_supervisor import load_meta_state
from doofus.metacognition.calibration import CalibrationObservation, summarize_calibration
from doofus.reports.clean_baseline import (
    baseline_certificate_json_path,
    contaminated_generations_from_marker,
    load_baseline_certificate,
    load_contamination_marker,
)
from doofus.supervisor.doofus_crash_recovery import load_checkpoint

KPI_STATE = STATE / "kpi_tracker.json"
KPI_HISTORY = STATE / "kpi_history.jsonl"
HOURLY_LAST = STATE / "hourly_kpi_last.json"
HOURLY_REPORT_DIR = SHARED / "hourly-kpi-reports"
HOURLY_LATEST_MD = SHARED / "DOOFUS-HOURLY-KPI-LATEST.md"
HOURLY_LATEST_JSON = SHARED / "DOOFUS-HOURLY-KPI-LATEST.json"
DEFAULT_CHAMPION_GEN = 1633
HOURLY_RETENTION_HOURS = 72


def champion_generation() -> int:
    return int(os.environ.get("DOOFUS_KPI_CHAMPION_GEN", str(DEFAULT_CHAMPION_GEN)))


def _reports_dir() -> Path:
    return STATE.parent / "reports"


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return any(row[1] == column for row in conn.execute(f"PRAGMA table_info({table})"))


def _since_gen_clause(gen: int) -> tuple[str, tuple[Any, ...]]:
    return "generation >= ?", (gen,)


def _composer_metrics(conn: sqlite3.Connection, since_gen: int) -> dict[str, Any]:
    out: dict[str, Any] = {
        "attempts": 0,
        "live_calls": 0,
        "successful_mutations": 0,
        "success_rate": None,
        "transport_breakdown": {},
        "classification_breakdown": {},
        "skips": 0,
        "fallbacks": 0,
    }
    if _table_exists(conn, "model_call_events"):
        rows = conn.execute(
            """
            SELECT classification, transport, provider, fallback_from, success,
                   COALESCE(attempted, CASE WHEN classification != 'DOOFUS_MODEL_GATE_BLOCKED' THEN 1 ELSE 0 END),
                   COALESCE(live, CASE WHEN classification = 'DOOFUS_MODEL_LIVE' THEN 1 ELSE 0 END),
                   COALESCE(skipped, CASE WHEN classification IN ('DOOFUS_MODEL_SKIPPED','DOOFUS_MODEL_GATE_BLOCKED') THEN 1 ELSE 0 END),
                   COALESCE(fallback_used, CASE WHEN fallback_from IS NOT NULL AND fallback_from != '' THEN 1 ELSE 0 END),
                   COUNT(*) AS n
            FROM model_call_events
            WHERE generation >= ?
            GROUP BY classification, transport, provider, fallback_from, success, attempted, live, skipped, fallback_used
            """,
            (since_gen,),
        ).fetchall()
        attempts = 0
        live_calls = 0
        successes = 0
        skips = 0
        fallbacks = 0
        transports: dict[str, int] = {}
        classes: dict[str, int] = {}
        for cls, transport, _provider, _fb, success, attempted, live, skipped, fallback_used, n in rows:
            attempts += n if attempted else 0
            live_calls += n if live else 0
            successes += n if success else 0
            skips += n if skipped else 0
            fallbacks += n if fallback_used else 0
            transports[transport or "unknown"] = transports.get(transport or "unknown", 0) + n
            classes[cls or "unknown"] = classes.get(cls or "unknown", 0) + n
        out.update({
            "attempts": attempts,
            "live_calls": live_calls,
            "successful_mutations": successes,
            "success_rate": round(successes / attempts, 4) if attempts else None,
            "transport_breakdown": transports,
            "classification_breakdown": classes,
            "skips": skips,
            "fallbacks": fallbacks,
        })
    else:
        rows = conn.execute(
            """
            SELECT provider, COUNT(*) FROM model_calls
            WHERE provider LIKE 'cursor%' OR provider IN ('cursor_agent_cli', 'cursor_sdk', 'dry_run')
            GROUP BY provider
            """
        ).fetchall()
        total = sum(n for _p, n in rows)
        out["attempts"] = total
        out["live_calls"] = sum(n for p, n in rows if "cursor" in (p or "") and p != "dry_run")
        out["transport_breakdown"] = {p: n for p, n in rows}
        if total:
            out["success_rate"] = round(out["live_calls"] / total, 4)
    return out


def _fallback_metrics(conn: sqlite3.Connection, since_gen: int) -> dict[str, Any]:
    if not _table_exists(conn, "model_call_events"):
        return {"fallback_events": 0, "fallback_rate": None, "fallback_reasons": {}}
    total = int(conn.execute(
        "SELECT COUNT(*) FROM model_call_events WHERE generation >= ? AND COALESCE(attempted, 1) = 1",
        (since_gen,),
    ).fetchone()[0])
    rows = conn.execute(
        """
        SELECT COALESCE(fallback_from, 'none'), COUNT(*)
        FROM model_call_events
        WHERE generation >= ? AND (
          (fallback_from IS NOT NULL AND fallback_from != '')
          OR COALESCE(fallback_used, 0) = 1
        )
        GROUP BY COALESCE(NULLIF(fallback_reason, ''), NULLIF(fallback_from, ''), 'unknown')
        """,
        (since_gen,),
    ).fetchall()
    fallback_events = sum(n for _r, n in rows)
    hybrid_rows = conn.execute(
        """
        SELECT COUNT(*) FROM model_call_events
        WHERE generation >= ? AND provider = 'openrouter' AND classification = 'DOOFUS_MODEL_LIVE'
        """,
        (since_gen,),
    ).fetchone()
    openrouter_after_cursor = int(hybrid_rows[0]) if hybrid_rows else 0
    return {
        "fallback_events": fallback_events,
        "fallback_rate": round(fallback_events / total, 4) if total else None,
        "fallback_reasons": {r: n for r, n in rows},
        "openrouter_hybrid_live_calls": openrouter_after_cursor,
    }


def _cost_per_promotion(conn: sqlite3.Connection, since_gen: int) -> dict[str, Any]:
    cost_row = conn.execute("SELECT COALESCE(SUM(cost_est), 0) FROM model_calls").fetchone()
    event_cost = 0.0
    if _table_exists(conn, "model_call_events"):
        event_cost = float(
            conn.execute(
                "SELECT COALESCE(SUM(cost_est), 0) FROM model_call_events WHERE generation >= ?",
                (since_gen,),
            ).fetchone()[0]
        )
    total_cost = float(cost_row[0] if cost_row else 0.0)
    promo_row = conn.execute(
        """
        SELECT COUNT(*)
        FROM promotions p
        JOIN candidates c ON c.candidate_id = p.candidate_id
        WHERE c.generation >= ?
        """,
        (since_gen,),
    ).fetchone()
    promos = int(promo_row[0] if promo_row else 0)
    since_promo_cost = event_cost if event_cost else total_cost
    return {
        "total_model_cost_usd": round(total_cost, 6),
        "cost_since_champion_gen_usd": round(since_promo_cost, 6),
        "promotions_since_champion_gen": promos,
        "cost_per_promotion_usd": round(since_promo_cost / promos, 6) if promos else None,
    }


def _replay_stability(conn: sqlite3.Connection, since_gen: int) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT
          COUNT(*) AS n,
          AVG(c.score_replay) AS avg_replay,
          MIN(c.score_replay) AS min_replay,
          AVG(CASE WHEN c.score_replay >= 0.45 THEN 1.0 ELSE 0.0 END) AS pass_rate
        FROM promotions p
        JOIN candidates c ON c.candidate_id = p.candidate_id
        WHERE c.generation >= ?
        """,
        (since_gen,),
    ).fetchone()
    reject_row = conn.execute(
        """
        SELECT AVG(c.score_replay)
        FROM rejections r
        JOIN candidates c ON c.candidate_id = r.candidate_id
        WHERE c.generation >= ? AND r.reason LIKE '%replay%'
        """,
        (since_gen,),
    ).fetchone()
    return {
        "promotions_count": int(row[0] if row and row[0] else 0),
        "avg_score_replay": round(float(row[1]), 4) if row and row[1] is not None else None,
        "min_score_replay": round(float(row[2]), 4) if row and row[2] is not None else None,
        "replay_gate_pass_rate": round(float(row[3]), 4) if row and row[3] is not None else None,
        "replay_rejection_avg_score": round(float(reject_row[0]), 4) if reject_row and reject_row[0] is not None else None,
    }


def _champion_defense(conn: sqlite3.Connection, since_gen: int) -> dict[str, Any]:
    checkpoint = load_checkpoint()
    best = get_best_ever()
    champion_baseline = float(checkpoint.get("baseline_score") or best.get("best_score") or 0)
    best_score = float(best.get("best_score") or best.get("best_ever_score") or 0)
    best_gen = best.get("best_generation")
    promos = conn.execute(
        """
        SELECT COUNT(*), MAX(c.score_total)
        FROM promotions p
        JOIN candidates c ON c.candidate_id = p.candidate_id
        WHERE c.generation >= ?
        """,
        (since_gen,),
    ).fetchone()
    high_rejects = conn.execute(
        """
        SELECT COUNT(*)
        FROM rejections r
        JOIN candidates c ON c.candidate_id = r.candidate_id
        WHERE c.generation >= ? AND c.score_total >= ?
        """,
        (since_gen, champion_baseline),
    ).fetchone()
    tournament = load_json(STATE / "challenger_tournaments.json", default={})
    return {
        "champion_generation_floor": since_gen,
        "checkpoint_baseline": champion_baseline,
        "best_ever_score": best_score,
        "best_ever_candidate_id": best.get("best_candidate_id"),
        "best_ever_generation": best_gen,
        "champion_held": best_score >= champion_baseline if champion_baseline else None,
        "champion_improved": best_score > champion_baseline + 0.0001 if champion_baseline else None,
        "promotions_since_floor": int(promos[0] if promos else 0),
        "max_promoted_score_since_floor": round(float(promos[1]), 4) if promos and promos[1] is not None else None,
        "high_score_rejections_since_floor": int(high_rejects[0] if high_rejects else 0),
        "tournament_count": tournament.get("tournament_count"),
        "last_tournament_winner": tournament.get("last_winner"),
    }


def _record_map_drift_event(
    conn: sqlite3.Connection,
    *,
    json_keys: list[str],
    sql_keys: list[str],
    repaired: bool,
    repair_reason: str = "",
    unrepaired_reason: str = "",
) -> None:
    missing_in_sql = sorted(set(json_keys) - set(sql_keys))
    missing_in_json = sorted(set(sql_keys) - set(json_keys))
    drift_count = len(missing_in_sql) + len(missing_in_json)
    conn.execute(
        """
        INSERT INTO map_elites_drift_events (
          timestamp_utc, json_cell_count, sql_cell_count, drift_count, missing_in_sql,
          missing_in_json, repaired, repair_reason, unrepaired_reason, created_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
        (
            _now(),
            len(json_keys),
            len(sql_keys),
            drift_count,
            json.dumps(missing_in_sql),
            json.dumps(missing_in_json),
            int(repaired),
            repair_reason or None,
            unrepaired_reason or None,
            _now(),
        ),
    )


def reconcile_map_elites_archive(*, auto_backfill: bool = True) -> dict[str, Any]:
    archive_raw = load_json(STATE / "map_elites_archive.json", default=[])
    entries = archive_raw if isinstance(archive_raw, list) else list((archive_raw or {}).get("cells", {}).values())
    json_entries = {str(e.get("cell_key")): e for e in entries if isinstance(e, dict) and e.get("cell_key")}
    init_db()
    conn = connect_metrics_db()
    try:
        sql_rows = conn.execute(
            """
            SELECT cell_key, measure_safety, measure_mutation, measure_arena, fitness, candidate_id, generation, updated_at
            FROM map_elites_cells
            """
        ).fetchall()
        sql_entries = {
            str(row[0]): {
                "cell_key": row[0],
                "measure_safety": row[1],
                "measure_mutation": row[2],
                "measure_arena": row[3],
                "fitness": row[4],
                "candidate_id": row[5],
                "generation": row[6],
                "updated_at": row[7],
            }
            for row in sql_rows
        }
        missing_in_sql = sorted(set(json_entries) - set(sql_entries))
        missing_in_json = sorted(set(sql_entries) - set(json_entries))
        mismatched = []
        mismatched_details = []
        for key in sorted(set(json_entries) & set(sql_entries)):
            j = json_entries[key]
            s = sql_entries[key]
            if (
                float(j.get("fitness") or 0) != float(s.get("fitness") or 0)
                or str(j.get("candidate_id")) != str(s.get("candidate_id"))
                or str(j.get("updated_at") or "") != str(s.get("updated_at") or "")
            ):
                mismatched.append(key)
                mismatched_details.append({
                    "cell_key": key,
                    "json_candidate_id": j.get("candidate_id"),
                    "sql_candidate_id": s.get("candidate_id"),
                    "json_fitness": j.get("fitness"),
                    "sql_fitness": s.get("fitness"),
                    "json_updated_at": j.get("updated_at"),
                    "sql_updated_at": s.get("updated_at"),
                })

        repaired = False
        repair_reasons: list[str] = []
        unrepaired_reason = ""
        if auto_backfill and missing_in_sql:
            try:
                for key in missing_in_sql:
                    e = json_entries[key]
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO map_elites_cells
                        (cell_key, measure_safety, measure_mutation, measure_arena, fitness, candidate_id, generation, updated_at)
                        VALUES (?,?,?,?,?,?,?,?)
                        """,
                        (
                            e.get("cell_key"),
                            e.get("measure_safety"),
                            e.get("measure_mutation"),
                            e.get("measure_arena"),
                            e.get("fitness"),
                            e.get("candidate_id"),
                            e.get("generation"),
                            e.get("updated_at"),
                        ),
                    )
                repaired = True
                repair_reasons.append("backfilled_sql_from_json")
                sql_entries.update({key: json_entries[key] for key in missing_in_sql})
                missing_in_sql = []
            except Exception as exc:
                unrepaired_reason = type(exc).__name__
        if auto_backfill and mismatched:
            try:
                for key in mismatched:
                    j = json_entries[key]
                    s = sql_entries[key]
                    if float(j.get("fitness") or 0) >= float(s.get("fitness") or 0):
                        conn.execute(
                            """
                            INSERT OR REPLACE INTO map_elites_cells
                            (cell_key, measure_safety, measure_mutation, measure_arena, fitness, candidate_id, generation, updated_at)
                            VALUES (?,?,?,?,?,?,?,?)
                            """,
                            (
                                j.get("cell_key"),
                                j.get("measure_safety"),
                                j.get("measure_mutation"),
                                j.get("measure_arena"),
                                j.get("fitness"),
                                j.get("candidate_id"),
                                j.get("generation"),
                                j.get("updated_at"),
                            ),
                        )
                        sql_entries[key] = dict(j)
                repaired = True
                repair_reasons.append("refreshed_sql_from_newer_json_cells")
                mismatched = []
            except Exception as exc:
                unrepaired_reason = type(exc).__name__
        non_doofus_only = []
        if missing_in_json:
            for key in missing_in_json:
                candidate_id = str(sql_entries.get(key, {}).get("candidate_id") or "")
                if not candidate_id.startswith("DOOFUS_"):
                    non_doofus_only.append(key)
        if missing_in_sql or missing_in_json or mismatched:
            if missing_in_json and len(non_doofus_only) == len(missing_in_json) and not missing_in_sql and not mismatched:
                unrepaired_reason = "sql_only_non_doofus_cells"
            elif not unrepaired_reason:
                unrepaired_reason = "drift_detected_without_safe_backfill"

        if missing_in_sql or missing_in_json or mismatched or repaired:
            _record_map_drift_event(
                conn,
                json_keys=list(json_entries),
                sql_keys=list(sql_entries),
                repaired=repaired,
                repair_reason=";".join(repair_reasons),
                unrepaired_reason=unrepaired_reason,
            )
            conn.commit()
        if repaired and not (missing_in_sql or missing_in_json or mismatched):
            sync_status = "repaired"
        elif missing_in_json and len(non_doofus_only) == len(missing_in_json) and not missing_in_sql and not mismatched:
            sync_status = "drift_explained_nondestructive"
        elif missing_in_sql or missing_in_json or mismatched:
            sync_status = "drift_detected"
        else:
            sync_status = "synced"
        return {
            "sync_status": sync_status,
            "json_cell_count": len(json_entries),
            "sql_cell_count": len(sql_entries),
            "missing_in_sql": missing_in_sql,
            "missing_in_json": missing_in_json,
            "mismatched_keys": mismatched,
            "mismatched_details": mismatched_details,
            "repaired": repaired,
            "repair_reason": ";".join(repair_reasons) or None,
            "unrepaired_reason": unrepaired_reason or None,
        }
    finally:
        conn.close()


def _map_elites_growth(conn: sqlite3.Connection) -> dict[str, Any]:
    sync = reconcile_map_elites_archive(auto_backfill=True)
    archive_raw = load_json(STATE / "map_elites_archive.json", default={"cells": {}})
    if isinstance(archive_raw, list):
        cells_json = archive_raw
        json_count = len(archive_raw)
    else:
        archive = archive_raw if isinstance(archive_raw, dict) else {}
        cells_json = archive.get("cells") or {}
        if isinstance(cells_json, dict):
            json_count = len(cells_json)
        elif isinstance(cells_json, list):
            json_count = len(cells_json)
        else:
            json_count = 0
    sql_count = 0
    occupancy = None
    if _table_exists(conn, "map_elites_cells"):
        sql_count = int(conn.execute("SELECT COUNT(*) FROM map_elites_cells").fetchone()[0])
        row = conn.execute("SELECT AVG(fitness), MAX(updated_at) FROM map_elites_cells").fetchone()
        avg_fitness = round(float(row[0]), 4) if row and row[0] is not None else None
        last_update = row[1] if row else None
    else:
        avg_fitness = None
        last_update = None
    history = load_json(KPI_STATE, default={}).get("map_elites_cell_history") or []
    history = (history + [{"ts": _now(), "json_cells": json_count, "sql_cells": sql_count}])[-200:]
    return {
        "json_archive_cells": json_count,
        "sql_archive_cells": sql_count,
        "avg_cell_fitness": avg_fitness,
        "last_cell_update": last_update,
        "sync_status": sync.get("sync_status"),
        "last_drift_reason": sync.get("unrepaired_reason") or sync.get("repair_reason"),
        "missing_in_sql": sync.get("missing_in_sql"),
        "missing_in_json": sync.get("missing_in_json"),
        "cell_history_points": len(history),
        "cell_history_latest": history[-3:] if history else [],
        "_history_append": history,
    }


def _meta_cadence(conn: sqlite3.Connection) -> dict[str, Any]:
    meta = load_meta_state()
    cycle = int(meta.get("cycle_count") or 0)
    gepa_every = int(os.environ.get("DOOFUS_GEPA_BATCH_EVERY", "3"))
    map_every = int(os.environ.get("DOOFUS_MAP_ELITES_MAINTAIN_EVERY", "8"))
    code_every = int(os.environ.get("DOOFUS_CODEEVOLVE_EVERY", "20"))
    gepa_traces = 0
    gepa_versions = 0
    code_rows = 0
    code_events = 0
    last_code_event: dict[str, Any] | None = None
    if _table_exists(conn, "gepa_traces"):
        gepa_traces = int(conn.execute("SELECT COUNT(*) FROM gepa_traces").fetchone()[0])
    if _table_exists(conn, "gepa_prompt_versions"):
        gepa_versions = int(conn.execute("SELECT COUNT(*) FROM gepa_prompt_versions").fetchone()[0])
    if _table_exists(conn, "codeevolve_generations"):
        code_rows = int(conn.execute("SELECT COUNT(*) FROM codeevolve_generations").fetchone()[0])
    if _table_exists(conn, "codeevolve_events"):
        code_events = int(conn.execute("SELECT COUNT(*) FROM codeevolve_events").fetchone()[0])
        row = conn.execute(
            """
            SELECT due, attempted, ran, skipped, skip_reason, gate_name, gate_details_sanitized, created_at
            FROM codeevolve_events
            ORDER BY id DESC LIMIT 1
            """
        ).fetchone()
        if row:
            last_code_event = {
                "due": bool(row[0]),
                "attempted": bool(row[1]),
                "ran": bool(row[2]),
                "skipped": bool(row[3]),
                "skip_reason": row[4],
                "gate_name": row[5],
                "gate_details_sanitized": row[6],
                "created_at": row[7],
            }
    return {
        "meta_cycle_count": cycle,
        "last_gepa_cycle": meta.get("last_gepa_cycle"),
        "last_map_cycle": meta.get("last_map_cycle"),
        "last_codeevolve_cycle": meta.get("last_codeevolve_cycle"),
        "cycles_until_gepa": max(0, gepa_every - (cycle - int(meta.get("last_gepa_cycle") or 0))),
        "cycles_until_map": max(0, map_every - (cycle - int(meta.get("last_map_cycle") or 0))),
        "cycles_until_codeevolve": max(0, code_every - (cycle - int(meta.get("last_codeevolve_cycle") or 0))),
        "gepa_traces_total": gepa_traces,
        "gepa_prompt_versions_total": gepa_versions,
        "codeevolve_generations_total": code_rows,
        "codeevolve_event_rows": code_events,
        "last_codeevolve_event": last_code_event,
        "cadence_config": {"gepa_every": gepa_every, "map_every": map_every, "codeevolve_every": code_every},
    }


def _sqlite_contention(conn: sqlite3.Connection) -> dict[str, Any]:
    probe_ok = True
    probe_err = None
    try:
        conn.execute("SELECT 1").fetchone()
    except sqlite3.OperationalError as exc:
        probe_ok = False
        probe_err = type(exc).__name__
    if not _table_exists(conn, "db_health_events"):
        return {"probe_ok": probe_ok, "probe_error": probe_err, "events_total": 0}
    total = int(conn.execute("SELECT COUNT(*) FROM db_health_events").fetchone()[0])
    locked = int(conn.execute(
        "SELECT COUNT(*) FROM db_health_events WHERE event_type = 'connect_locked'"
    ).fetchone()[0])
    retries = int(conn.execute(
        "SELECT COUNT(*) FROM db_health_events WHERE event_type = 'connect_retry'"
    ).fetchone()[0])
    slow = int(conn.execute(
        "SELECT COUNT(*) FROM db_health_events WHERE event_type = 'connect_slow'"
    ).fetchone()[0])
    recent = conn.execute(
        """
        SELECT event_type, retries, latency_ms, detail, created_at
        FROM db_health_events
        ORDER BY id DESC LIMIT 5
        """
    ).fetchall()
    return {
        "probe_ok": probe_ok,
        "probe_error": probe_err,
        "events_total": total,
        "locked_events": locked,
        "retry_events": retries,
        "slow_connect_events": slow,
        "recent_events": [
            {"event_type": r[0], "retries": r[1], "latency_ms": r[2], "detail": r[3], "created_at": r[4]}
            for r in recent
        ],
    }


def _champion_defense_status(champ: dict[str, Any]) -> str:
    if not champ:
        return "unknown"
    if champ.get("promotions_since_floor") or champ.get("high_score_rejections_since_floor"):
        return "challenged"
    if champ.get("champion_held"):
        return "held"
    return "regression"


def _contamination_adjusted_progress(conn: sqlite3.Connection, snapshot: dict[str, Any]) -> dict[str, Any]:
    certificate = load_baseline_certificate()
    marker = load_contamination_marker()
    checkpoint = snapshot.get("checkpoint") or {}
    operational_generation = int(checkpoint.get("generation") or 0)
    excluded = contaminated_generations_from_marker(marker)
    baseline_type = certificate.get("baseline_type")
    certified_baseline_generation = certificate.get("baseline_generation")
    certified_at = str(certificate.get("timestamp_utc") or "")
    status = "FAIL"
    if baseline_type == "CERTIFIED_POST_CONTAMINATION_REBASE_BASELINE":
        status = "CERTIFIED_REBASE_EXCLUSIONS_ACTIVE"
    elif baseline_type == "RESTORED_CLEAN_BASELINE":
        status = "CLEAN"

    promotions_sql = """
        SELECT COUNT(*)
        FROM promotions p
        JOIN candidates c ON c.candidate_id = p.candidate_id
        WHERE c.generation >= ?
    """
    composer_sql = """
        SELECT COUNT(*)
        FROM model_call_events
        WHERE generation >= ?
          AND classification = 'DOOFUS_MODEL_LIVE'
          AND COALESCE(success, 0) = 1
          AND COALESCE(live, 0) = 1
    """
    params: list[Any] = [int(certified_baseline_generation or operational_generation or 0)]
    promo_params: list[Any] = list(params)
    composer_params: list[Any] = list(params)
    if certified_at:
        promotions_sql += " AND COALESCE(p.created_at, '') >= ?"
        composer_sql += " AND COALESCE(created_at, '') >= ?"
        promo_params.append(certified_at)
        composer_params.append(certified_at)
    valid_promotions = int(conn.execute(promotions_sql, tuple(promo_params)).fetchone()[0]) if _table_exists(conn, "promotions") else 0
    valid_composer = int(conn.execute(composer_sql, tuple(composer_params)).fetchone()[0]) if _table_exists(conn, "model_call_events") else 0
    return {
        "baseline_type": baseline_type or "NONE",
        "baseline_certificate_path": str(baseline_certificate_json_path()),
        "operational_generation": operational_generation,
        "certified_baseline_generation": certified_baseline_generation,
        "excluded_contaminated_generations": excluded,
        "champion_defense_status": _champion_defense_status(snapshot.get("champion_defense") or {}),
        "valid_live_promotions_since_certified_baseline": valid_promotions,
        "valid_live_composer_events_since_certified_baseline": valid_composer,
        "contamination_adjusted_progress_status": status,
        "contamination_marker_active_block": bool(marker.get("active_contamination_block", False)),
    }


def _record_champion_defense_event(conn: sqlite3.Connection, snapshot: dict[str, Any]) -> None:
    champ = snapshot.get("champion_defense") or {}
    replay = snapshot.get("promotion_replay_stability") or {}
    generation = int((snapshot.get("checkpoint") or {}).get("generation") or 0)
    champion_status = "held"
    if champ.get("champion_improved"):
        champion_status = "held"
    if champ.get("promotions_since_floor"):
        champion_status = "challenged"
    if champ.get("high_score_rejections_since_floor"):
        champion_status = "challenged"
    conn.execute(
        """
        INSERT INTO champion_defense_events (
          timestamp_utc, generation, baseline_fitness, best_ever_fitness, best_ever_candidate,
          latest_tournament_winner, promotions_since_floor, high_score_rejections_since_floor,
          champion_status, replay_required, replay_passed, created_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            _now(),
            generation,
            champ.get("checkpoint_baseline"),
            champ.get("best_ever_score"),
            champ.get("best_ever_candidate_id"),
            champ.get("last_tournament_winner"),
            champ.get("promotions_since_floor") or 0,
            champ.get("high_score_rejections_since_floor") or 0,
            champion_status,
            int(bool(champ.get("promotions_since_floor"))),
            None if replay.get("replay_gate_pass_rate") is None else int(float(replay.get("replay_gate_pass_rate") or 0) >= 1.0),
            _now(),
        ),
    )


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _metacognitive_calibration(conn: sqlite3.Connection) -> dict[str, Any]:
    """Return the tracked calibration KPI across recent resolved predictions."""
    limit = max(1, int(os.environ.get("DOOFUS_KPI_CALIBRATION_WINDOW", "500")))
    if not _table_exists(conn, "metacognitive_predictions"):
        return {
            "sample_count": 0,
            "brier_score": None,
            "brier_skill": None,
            "expected_calibration_error": None,
            "experimental": True,
        }
    rows = conn.execute(
        """SELECT probability_non_regression, actual_non_regression, predicted_fitness,
                  actual_fitness, interval_low, interval_high, recommended_action
           FROM metacognitive_predictions
           WHERE resolved_at IS NOT NULL
           ORDER BY created_at DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    observations = [
        CalibrationObservation(
            predicted_probability=float(row[0]),
            actual_outcome=bool(row[1]),
            predicted_fitness=float(row[2]),
            actual_fitness=float(row[3]),
            interval_low=float(row[4]),
            interval_high=float(row[5]),
            recommended_action=str(row[6]),
        )
        for row in rows
    ]
    if not observations:
        return {
            "sample_count": 0,
            "brier_score": None,
            "brier_skill": None,
            "expected_calibration_error": None,
            "experimental": True,
        }
    summary = summarize_calibration(observations)
    payload = summary.model_dump()
    payload["brier_score"] = round(summary.brier_score, 6)
    payload["brier_skill"] = round(1.0 - summary.brier_score, 6)
    payload["expected_calibration_error"] = round(summary.expected_calibration_error, 6)
    return payload


def capture_kpi_snapshot(*, since_gen: int | None = None) -> dict[str, Any]:
    since_gen = since_gen if since_gen is not None else champion_generation()
    init_db()
    conn = connect_metrics_db()
    try:
        map_data = _map_elites_growth(conn)
        history_append = map_data.pop("_history_append", [])
        snapshot = {
            "classification": "DOOFUS_SOTA_KPI_SNAPSHOT",
            "captured_at": _now(),
            "since_generation": since_gen,
            "checkpoint": load_checkpoint(),
            "composer_mutations": _composer_metrics(conn, since_gen),
            "fallback": _fallback_metrics(conn, since_gen),
            "cost_per_promotion": _cost_per_promotion(conn, since_gen),
            "promotion_replay_stability": _replay_stability(conn, since_gen),
            "champion_defense": _champion_defense(conn, since_gen),
            "map_elites_growth": map_data,
            "meta_cadence": _meta_cadence(conn),
            "metacognitive_calibration": _metacognitive_calibration(conn),
            "sqlite_contention": _sqlite_contention(conn),
        }
        snapshot["baseline_certification"] = _contamination_adjusted_progress(conn, snapshot)
        if _table_exists(conn, "champion_defense_events"):
            _record_champion_defense_event(conn, snapshot)
            conn.commit()
    finally:
        conn.close()

    prev = load_json(KPI_STATE, default={})
    save_json(KPI_STATE, {**snapshot, "map_elites_cell_history": history_append})
    KPI_HISTORY.parent.mkdir(parents=True, exist_ok=True)
    with KPI_HISTORY.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(snapshot, default=str) + "\n")
    return snapshot


def _proposals_returned(model_result: dict[str, Any], validation: dict[str, Any]) -> int:
    if isinstance(model_result.get("proposals"), list):
        return len(model_result["proposals"])
    proposal = validation.get("proposal")
    if isinstance(proposal, dict) and isinstance(proposal.get("proposals"), list):
        return len(proposal["proposals"])
    return int(model_result.get("proposals_returned") or 0)


def _gate_status_text(gate: dict[str, Any]) -> str:
    if gate.get("allowed"):
        return "allowed"
    reason = gate.get("reason")
    return f"blocked:{reason}" if reason else "blocked"


def _proof_gate_status(scored: list[dict]) -> str:
    proof_rejections = sum(1 for c in scored if "proof_density" in str(c.get("rejection_reason") or ""))
    if proof_rejections:
        return f"rejected:{proof_rejections}"
    if any(c.get("status") == "promoted" for c in scored):
        return "passed"
    return "not_triggered"


def _tier3_gate_status(scored: list[dict]) -> str:
    if not scored:
        return "not_triggered"
    high_score = [c for c in scored if float(c.get("score_total") or 0) >= 0.85]
    if not high_score:
        return "not_required"
    if any("tier3" in str(c.get("rejection_reason") or "") for c in scored):
        return "blocked"
    return "audit_only_or_passed"


def record_cycle_model_event(
    generation: int,
    model_result: dict[str, Any],
    *,
    run_id: str,
    route: dict[str, Any],
    gate: dict[str, Any],
    model_context: dict[str, Any],
    cfg: Any,
    candidates: list[dict],
    scored: list[dict],
) -> None:
    validation = model_result.get("proposal_validation") or {}
    classification = str(model_result.get("classification") or "")
    attempted = bool(model_result.get("attempted")) or classification in {"DOOFUS_MODEL_LIVE", "DOOFUS_MODEL_DRY_RUN"}
    proposals_applied = int(model_result.get("proposals_applied_count") or (1 if model_result.get("proposal_applied") else 0))
    skipped = bool(model_result.get("skipped")) or not attempted or proposals_applied == 0
    skip_reason = str(model_result.get("skip_reason") or model_result.get("reason") or "")
    live = classification == "DOOFUS_MODEL_LIVE" and model_result.get("mode") == "live"
    dry_run = classification == "DOOFUS_MODEL_DRY_RUN" or model_result.get("mode") == "dry_run"
    fallback_reason = str(model_result.get("cursor_fallback_from") or "")
    fallback_used = bool(fallback_reason)
    transport = str(model_result.get("transport") or model_result.get("provider") or "")
    tournament = load_json(STATE / "challenger_tournaments.json", default={})
    explicit_provider = os.environ.get("DOOFUS_MODEL_PROVIDER", "").strip().lower()
    provider_requested = explicit_provider or "auto"
    provider_resolved = str(route.get("provider_selected") or model_result.get("provider_selected") or "")
    model_requested = str(route.get("model_name") or os.environ.get("DOOFUS_CURSOR_MODEL") or os.environ.get("DOOFUS_MODEL_NAME") or "")
    model_resolved = str(model_result.get("cursor_model") or route.get("model_name") or model_requested)
    cursor_cli_auth = False
    try:
        from doofus.model_router.cursor_agent_cli import probe_agent_auth

        cursor_cli_auth = bool(probe_agent_auth().get("logged_in"))
    except Exception:
        pass
    try:
        from doofus.model_router.model_call_ledger import log_sqlite_health, record_model_event

        record_model_event(
            generation=generation,
            model_result=model_result,
            run_id=run_id,
            cycle_id=None,
            tournament_count=int(tournament.get("tournament_count") or 0),
            provider_requested=provider_requested,
            provider_resolved=provider_resolved,
            model_requested=model_requested,
            model_resolved=model_resolved,
            cursor_agent_cli_authenticated=cursor_cli_auth,
            cursor_api_key_present=bool(os.environ.get("CURSOR_API_KEY", "").strip()),
            prefer_cursor=os.environ.get("DOOFUS_PREFER_CURSOR", "0") == "1",
            hybrid_fallback_enabled=os.environ.get("DOOFUS_CURSOR_HYBRID_FALLBACK", "1") == "1",
            mutation_batch_size=int(model_result.get("mutation_batch_size") or os.environ.get("DOOFUS_CURSOR_MUTATION_BATCH", "1")),
            model_guided_weight=float(os.environ.get("DOOFUS_MODEL_GUIDED_WEIGHT", "0") or 0),
            attempted=attempted,
            skipped=skipped,
            skip_reason=skip_reason,
            live=live,
            dry_run=dry_run,
            fallback_used=fallback_used,
            fallback_provider="openrouter" if fallback_used else "",
            fallback_reason=fallback_reason,
            proposals_requested=int(model_result.get("proposals_requested") or model_context.get("candidate_count") or len(candidates) or 0),
            proposals_returned=_proposals_returned(model_result, validation),
            proposals_applied=proposals_applied,
            proposal_valid=bool(validation.get("valid")),
            duration_ms=float(model_result.get("duration_ms") or 0.0),
            budget_gate_status=_gate_status_text(gate),
            proof_gate_status=_proof_gate_status(scored),
            tier3_gate_status=_tier3_gate_status(scored),
        )
    except Exception as exc:
        try:
            from doofus.model_router.model_call_ledger import log_sqlite_health

            log_sqlite_health(
                event_type="model_event_insert_failed",
                detail=type(exc).__name__,
            )
        except Exception:
            pass


def export_kpi_to_shared(snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    snapshot = snapshot or capture_kpi_snapshot()
    SHARED.mkdir(parents=True, exist_ok=True)
    (SHARED / "DOOFUS-SOTA-KPI-SNAPSHOT.json").write_text(json.dumps(snapshot, indent=2, default=str), encoding="utf-8")
    lines = [
        "# Doofus SOTA KPI Tracker",
        "",
        f"Captured: {snapshot.get('captured_at')}",
        f"Since generation: {snapshot.get('since_generation')}",
        "",
        "## Composer mutations",
        json.dumps(snapshot.get("composer_mutations"), indent=2),
        "",
        "## Fallback",
        json.dumps(snapshot.get("fallback"), indent=2),
        "",
        "## Cost per promotion",
        json.dumps(snapshot.get("cost_per_promotion"), indent=2),
        "",
        "## Promotion replay stability",
        json.dumps(snapshot.get("promotion_replay_stability"), indent=2),
        "",
        "## Champion defense",
        json.dumps(snapshot.get("champion_defense"), indent=2),
        "",
        "## MAP-Elites growth",
        json.dumps(snapshot.get("map_elites_growth"), indent=2),
        "",
        "## Meta cadence (GEPA/MAP/CodeEvolve)",
        json.dumps(snapshot.get("meta_cadence"), indent=2),
        "",
        "## Metacognitive calibration",
        json.dumps(snapshot.get("metacognitive_calibration"), indent=2),
        "",
        "## SQLite contention",
        json.dumps(snapshot.get("sqlite_contention"), indent=2),
        "",
        "## Baseline certification / contamination accounting",
        json.dumps(snapshot.get("baseline_certification"), indent=2),
        "",
    ]
    (SHARED / "DOOFUS-SOTA-KPI-TRACKER.md").write_text("\n".join(lines), encoding="utf-8")
    return {"classification": "DOOFUS_KPI_EXPORTED", "path": str(SHARED)}


def maybe_refresh_kpi_snapshot(*, every_n_cycles: int = 1, generation: int | None = None) -> dict[str, Any] | None:
    gen = generation if generation is not None else int(load_checkpoint().get("generation") or 0)
    if every_n_cycles <= 1 or gen % every_n_cycles == 0:
        snap = capture_kpi_snapshot()
        export_kpi_to_shared(snap)
        return snap
    return None


def _num_delta(current: Any, previous: Any) -> float | None:
    try:
        if current is None or previous is None:
            return None
        return round(float(current) - float(previous), 4)
    except (TypeError, ValueError):
        return None


def _fmt_delta(delta: float | None, *, suffix: str = "") -> str:
    if delta is None:
        return "n/a"
    sign = "+" if delta > 0 else ""
    return f"{sign}{delta}{suffix}"


def build_hourly_report_markdown(snapshot: dict[str, Any], previous: dict[str, Any] | None) -> str:
    prev = previous or {}
    comp = snapshot.get("composer_mutations") or {}
    pcomp = prev.get("composer_mutations") or {}
    fb = snapshot.get("fallback") or {}
    pfb = prev.get("fallback") or {}
    cost = snapshot.get("cost_per_promotion") or {}
    pcost = prev.get("cost_per_promotion") or {}
    replay = snapshot.get("promotion_replay_stability") or {}
    preplay = prev.get("promotion_replay_stability") or {}
    champ = snapshot.get("champion_defense") or {}
    pchamp = prev.get("champion_defense") or {}
    mapg = snapshot.get("map_elites_growth") or {}
    pmapg = prev.get("map_elites_growth") or {}
    meta = snapshot.get("meta_cadence") or {}
    pmeta = prev.get("meta_cadence") or {}
    calibration = snapshot.get("metacognitive_calibration") or {}
    pcalibration = prev.get("metacognitive_calibration") or {}
    sql = snapshot.get("sqlite_contention") or {}
    psql = prev.get("sqlite_contention") or {}
    base = snapshot.get("baseline_certification") or {}
    ckpt = snapshot.get("checkpoint") or {}
    prev_ckpt = prev.get("checkpoint") or {}

    gen = ckpt.get("generation")
    prev_gen = prev_ckpt.get("generation")
    gen_delta = _num_delta(gen, prev_gen)

    lines = [
        "# Doofus Hourly KPI Report",
        "",
        f"**Captured:** {snapshot.get('captured_at')}",
        f"**Tracking since generation:** {snapshot.get('since_generation')}",
        "",
        "## Executive summary",
        "",
        f"- Generation: **{gen}** ({_fmt_delta(gen_delta)} vs last hour)",
        f"- Baseline: **{ckpt.get('baseline_score')}**",
        f"- Composer success rate: **{comp.get('success_rate')}** ({_fmt_delta(_num_delta(comp.get('success_rate'), pcomp.get('success_rate')))})",
        f"- Fallback rate: **{fb.get('fallback_rate')}** ({_fmt_delta(_num_delta(fb.get('fallback_rate'), pfb.get('fallback_rate')))})",
        f"- Cost / promotion: **{cost.get('cost_per_promotion_usd')}** USD",
        f"- Promotions since floor: **{champ.get('promotions_since_floor')}** ({_fmt_delta(_num_delta(champ.get('promotions_since_floor'), pchamp.get('promotions_since_floor')))})",
        f"- MAP-Elites cells: **{mapg.get('sql_archive_cells')}** ({_fmt_delta(_num_delta(mapg.get('sql_archive_cells'), pmapg.get('sql_archive_cells')))})",
        f"- Metacognitive Brier score: **{calibration.get('brier_score')}** ({_fmt_delta(_num_delta(calibration.get('brier_score'), pcalibration.get('brier_score')))})",
        f"- SQLite lock events: **{sql.get('locked_events')}** ({_fmt_delta(_num_delta(sql.get('locked_events'), psql.get('locked_events')))})",
        f"- Progress accounting: **{base.get('contamination_adjusted_progress_status')}**",
        "",
        "## Composer mutation success",
        "",
        "| Metric | Now | Delta (1h) |",
        "|--------|-----|------------|",
        f"| Attempts | {comp.get('attempts')} | {_fmt_delta(_num_delta(comp.get('attempts'), pcomp.get('attempts')))} |",
        f"| Live calls | {comp.get('live_calls')} | {_fmt_delta(_num_delta(comp.get('live_calls'), pcomp.get('live_calls')))} |",
        f"| Successful mutations | {comp.get('successful_mutations')} | {_fmt_delta(_num_delta(comp.get('successful_mutations'), pcomp.get('successful_mutations')))} |",
        f"| Success rate | {comp.get('success_rate')} | {_fmt_delta(_num_delta(comp.get('success_rate'), pcomp.get('success_rate')))} |",
        "",
        f"Transport: `{json.dumps(comp.get('transport_breakdown') or {})}`",
        "",
        "## Fallback frequency",
        "",
        f"- Fallback events: **{fb.get('fallback_events')}** ({_fmt_delta(_num_delta(fb.get('fallback_events'), pfb.get('fallback_events')))})",
        f"- Fallback rate: **{fb.get('fallback_rate')}**",
        f"- OpenRouter hybrid live calls: **{fb.get('openrouter_hybrid_live_calls')}**",
        f"- Reasons: `{json.dumps(fb.get('fallback_reasons') or {})}`",
        "",
        "## Cost per promoted candidate",
        "",
        f"- Total model cost: **${cost.get('total_model_cost_usd')}** ({_fmt_delta(_num_delta(cost.get('total_model_cost_usd'), pcost.get('total_model_cost_usd')))})",
        f"- Cost since champion gen: **${cost.get('cost_since_champion_gen_usd')}**",
        f"- Promotions since floor: **{cost.get('promotions_since_champion_gen')}**",
        f"- **Cost / promotion: ${cost.get('cost_per_promotion_usd')}**",
        "",
        "## Promotion replay stability",
        "",
        f"- Promotions measured: **{replay.get('promotions_count')}**",
        f"- Avg score_replay: **{replay.get('avg_score_replay')}** ({_fmt_delta(_num_delta(replay.get('avg_score_replay'), preplay.get('avg_score_replay')))})",
        f"- Min score_replay: **{replay.get('min_score_replay')}**",
        f"- Replay gate pass rate: **{replay.get('replay_gate_pass_rate')}**",
        "",
        f"## Champion defense (gen {snapshot.get('since_generation')}+)",
        "",
        f"- Checkpoint baseline: **{champ.get('checkpoint_baseline')}**",
        f"- Best ever: **{champ.get('best_ever_score')}** ({champ.get('best_ever_candidate_id')})",
        f"- Champion held: **{champ.get('champion_held')}** | improved: **{champ.get('champion_improved')}**",
        f"- Promotions since floor: **{champ.get('promotions_since_floor')}**",
        f"- High-score rejections: **{champ.get('high_score_rejections_since_floor')}**",
        f"- Last tournament winner: `{champ.get('last_tournament_winner')}`",
        "",
        "## MAP-Elites archive growth",
        "",
        f"- JSON cells: **{mapg.get('json_archive_cells')}** | SQL cells: **{mapg.get('sql_archive_cells')}**",
        f"- Avg fitness: **{mapg.get('avg_cell_fitness')}** ({_fmt_delta(_num_delta(mapg.get('avg_cell_fitness'), pmapg.get('avg_cell_fitness')))})",
        f"- Last update: {mapg.get('last_cell_update')}",
        "",
        "## GEPA / MAP / CodeEvolve cadence",
        "",
        f"- Meta cycle: **{meta.get('meta_cycle_count')}** ({_fmt_delta(_num_delta(meta.get('meta_cycle_count'), pmeta.get('meta_cycle_count')))})",
        f"- Last GEPA cycle: **{meta.get('last_gepa_cycle')}** | until next: **{meta.get('cycles_until_gepa')}**",
        f"- Last MAP cycle: **{meta.get('last_map_cycle')}** | until next: **{meta.get('cycles_until_map')}**",
        f"- Last CodeEvolve cycle: **{meta.get('last_codeevolve_cycle')}** | until next: **{meta.get('cycles_until_codeevolve')}**",
        f"- GEPA traces: **{meta.get('gepa_traces_total')}** | prompt versions: **{meta.get('gepa_prompt_versions_total')}**",
        f"- CodeEvolve generations: **{meta.get('codeevolve_generations_total')}**",
        "",
        "## Metacognitive calibration KPI",
        "",
        f"- Resolved predictions: **{calibration.get('sample_count')}**",
        f"- Brier score (lower is better): **{calibration.get('brier_score')}**",
        f"- Brier skill (1 - Brier): **{calibration.get('brier_skill')}**",
        f"- Expected calibration error: **{calibration.get('expected_calibration_error')}**",
        f"- Experimental (<100 samples): **{calibration.get('experimental')}**",
        "",
        "## SQLite contention",
        "",
        f"- Probe OK: **{sql.get('probe_ok')}**",
        f"- Locked events: **{sql.get('locked_events')}** | retries: **{sql.get('retry_events')}** | slow: **{sql.get('slow_connect_events')}**",
        "",
        "## Certified baseline / contamination accounting",
        "",
        f"- Operational generation: **{base.get('operational_generation')}**",
        f"- Certified baseline generation: **{base.get('certified_baseline_generation')}**",
        f"- Excluded contaminated generations: **{base.get('excluded_contaminated_generations')}**",
        f"- Champion defense status: **{base.get('champion_defense_status')}**",
        f"- Valid live promotions since certified baseline: **{base.get('valid_live_promotions_since_certified_baseline')}**",
        f"- Valid live Composer events since certified baseline: **{base.get('valid_live_composer_events_since_certified_baseline')}**",
        f"- Accounting status: **{base.get('contamination_adjusted_progress_status')}**",
        "",
        "---",
        "",
        "Full JSON: `DOOFUS-HOURLY-KPI-LATEST.json`",
        "",
    ]
    return "\n".join(lines)


def _hourly_stamp(iso_ts: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    except ValueError:
        dt = datetime.now(timezone.utc)
    return dt.strftime("%Y%m%dT%H0000Z")


def _prune_hourly_reports() -> int:
    if not HOURLY_REPORT_DIR.exists():
        return 0
    cutoff = datetime.now(timezone.utc).timestamp() - HOURLY_RETENTION_HOURS * 3600
    removed = 0
    for path in HOURLY_REPORT_DIR.glob("hourly-*"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError:
            pass
    return removed


def publish_hourly_kpi_report(*, chat_only: bool = True) -> dict[str, Any]:
    """Capture KPIs and prepare update (chat-first; optional shared export when chat_only=False)."""
    previous = load_json(HOURLY_LAST, default={})
    snapshot = capture_kpi_snapshot()
    markdown = build_hourly_report_markdown(snapshot, previous if previous else None)
    stamp = _hourly_stamp(str(snapshot.get("captured_at") or _now()))

    chat_update = STATE / "kpi_chat_update.md"
    chat_json = STATE / "kpi_chat_update.json"
    chat_update.write_text(markdown, encoding="utf-8")
    chat_json.write_text(json.dumps(snapshot, indent=2, default=str), encoding="utf-8")
    save_json(HOURLY_LAST, snapshot)

    result = {
        "classification": "DOOFUS_KPI_CHAT_UPDATE",
        "captured_at": snapshot.get("captured_at"),
        "chat_markdown": str(chat_update),
        "chat_json": str(chat_json),
        "generation": (snapshot.get("checkpoint") or {}).get("generation"),
        "chat_only": chat_only,
    }

    if not chat_only:
        export_kpi_to_shared(snapshot)
        HOURLY_REPORT_DIR.mkdir(parents=True, exist_ok=True)
        archive_md = HOURLY_REPORT_DIR / f"hourly-{stamp}.md"
        archive_json = HOURLY_REPORT_DIR / f"hourly-{stamp}.json"
        archive_md.write_text(markdown, encoding="utf-8")
        archive_json.write_text(json.dumps(snapshot, indent=2, default=str), encoding="utf-8")
        HOURLY_LATEST_MD.write_text(markdown, encoding="utf-8")
        HOURLY_LATEST_JSON.write_text(json.dumps(snapshot, indent=2, default=str), encoding="utf-8")
        result.update({
            "classification": "DOOFUS_HOURLY_KPI_REPORT",
            "latest_markdown": str(HOURLY_LATEST_MD),
            "archive_markdown": str(archive_md),
            "pruned_old_reports": _prune_hourly_reports(),
        })

    (STATE / "kpi_scheduler_last_run.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result
