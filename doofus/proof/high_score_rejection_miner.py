"""High-score rejected candidate miner — bounded, deadline-aware, progress-abortable."""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any

from doofus.core.doofus_paths import METRICS_DB
from doofus.core.doofus_state import init_db
from doofus.proof.high_score_miner_telemetry import record_miner_event
from doofus.scoring.promotion_gate import PROMOTION_THRESHOLD

MINER_DEFERRED_DEADLINE = "HIGH_SCORE_MINER_DEFERRED_DEADLINE"
MINER_DEADLINE_EXCEEDED = "MINER_DEADLINE_EXCEEDED"
MINER_PROGRESS_ABORT = "MINER_PROGRESS_ABORT"
DEFAULT_QUERY_BUDGET_MS = 25_000.0
ENRICH_BUDGET_MS = 5_000.0


class MinerQueryAborted(RuntimeError):
    pass


def _past_deadline(deadline_monotonic: float | None) -> bool:
    return deadline_monotonic is not None and time.monotonic() >= deadline_monotonic


def _remaining_ms(deadline_monotonic: float | None) -> float:
    if deadline_monotonic is None:
        return float("inf")
    return max(0.0, (deadline_monotonic - time.monotonic()) * 1000.0)


def _empty_result(
    *,
    min_score: float,
    classification: str,
    timed_out: bool = False,
    timed_out_stage: str | None = None,
    decision: str | None = None,
) -> dict[str, Any]:
    return {
        "min_score": min_score,
        "count_score_gte_threshold": 0,
        "top_100": [],
        "proof_density_blocked_top_50": [],
        "closest_to_promotion_top_25": [],
        "best_ever": {},
        "timed_out": timed_out,
        "timed_out_stage": timed_out_stage,
        "classification": classification,
        "decision": decision or classification,
    }


def connect_miner_db(
    *,
    db_path: Path | None = None,
    readonly: bool = False,
    deadline_monotonic: float | None = None,
    progress_abort: bool = True,
) -> sqlite3.Connection:
    path = db_path or METRICS_DB
    if readonly:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5.0)
    else:
        if not readonly:
            init_db(path)
        conn = sqlite3.connect(path, timeout=10.0)
    conn.row_factory = sqlite3.Row
    if progress_abort and deadline_monotonic is not None:

        def _handler() -> int:
            if _past_deadline(deadline_monotonic):
                return 1
            return 0

        conn.set_progress_handler(_handler, 1000)
    return conn


def _execute_bounded_query(
    conn: sqlite3.Connection,
    *,
    query_name: str,
    sql: str,
    params: tuple[Any, ...],
    deadline_monotonic: float | None,
    limit: int | None,
    generation: int | None,
    db_path: Path | None,
    progress_abort_enabled: bool,
) -> list[sqlite3.Row]:
    if _past_deadline(deadline_monotonic):
        record_miner_event(
            step="high_score_miner_query_timeout",
            status="timeout",
            generation=generation,
            deadline_monotonic=deadline_monotonic,
            query_name=query_name,
            limit=limit,
            db_path=str(db_path or METRICS_DB),
            progress_abort_enabled=progress_abort_enabled,
            decision=MINER_DEADLINE_EXCEEDED,
        )
        raise MinerQueryAborted(f"{query_name}_before_start")

    record_miner_event(
        step="high_score_miner_query_start",
        status="started",
        generation=generation,
        deadline_monotonic=deadline_monotonic,
        query_name=query_name,
        limit=limit,
        db_path=str(db_path or METRICS_DB),
        progress_abort_enabled=progress_abort_enabled,
    )
    started = time.perf_counter()
    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError as exc:
        duration_ms = (time.perf_counter() - started) * 1000.0
        if "interrupted" in str(exc).lower() or _past_deadline(deadline_monotonic):
            record_miner_event(
                step="high_score_miner_progress_abort",
                status="abort",
                generation=generation,
                deadline_monotonic=deadline_monotonic,
                query_name=query_name,
                query_duration_ms=duration_ms,
                limit=limit,
                db_path=str(db_path or METRICS_DB),
                progress_abort_enabled=progress_abort_enabled,
                decision=MINER_PROGRESS_ABORT,
                error_type=type(exc).__name__,
                error_message_sanitized=str(exc)[:240],
            )
            raise MinerQueryAborted(query_name) from exc
        record_miner_event(
            step="high_score_miner_query_end",
            status="error",
            generation=generation,
            deadline_monotonic=deadline_monotonic,
            query_name=query_name,
            query_duration_ms=duration_ms,
            limit=limit,
            db_path=str(db_path or METRICS_DB),
            progress_abort_enabled=progress_abort_enabled,
            error_type=type(exc).__name__,
            error_message_sanitized=str(exc)[:240],
        )
        raise
    duration_ms = (time.perf_counter() - started) * 1000.0
    record_miner_event(
        step="high_score_miner_query_end",
        status="ok",
        generation=generation,
        deadline_monotonic=deadline_monotonic,
        query_name=query_name,
        query_duration_ms=duration_ms,
        rows_returned=len(rows),
        limit=limit,
        db_path=str(db_path or METRICS_DB),
        progress_abort_enabled=progress_abort_enabled,
    )
    if _past_deadline(deadline_monotonic):
        record_miner_event(
            step="high_score_miner_query_timeout",
            status="timeout",
            generation=generation,
            deadline_monotonic=deadline_monotonic,
            query_name=query_name,
            query_duration_ms=duration_ms,
            limit=limit,
            db_path=str(db_path or METRICS_DB),
            progress_abort_enabled=progress_abort_enabled,
            decision=MINER_DEADLINE_EXCEEDED,
        )
        raise MinerQueryAborted(f"{query_name}_after_query")
    return rows


def _derive_slices(rows: list[dict[str, Any]]) -> tuple[list[dict], list[dict]]:
    proof_blocked = [
        r
        for r in rows
        if "proof" in str(r.get("rejection_reason") or "").lower()
        or r.get("rejection_reason") == "proof_density_gate"
    ][:50]
    closest = rows[:25]
    return proof_blocked, closest


def _enrich_rows(
    conn: sqlite3.Connection,
    rows: list[dict[str, Any]],
    *,
    deadline_monotonic: float | None,
    generation: int | None,
    db_path: Path | None,
) -> list[dict[str, Any]]:
    if not rows or _remaining_ms(deadline_monotonic) < ENRICH_BUDGET_MS:
        record_miner_event(
            step="high_score_miner_partial_result",
            status="skipped_enrichment",
            generation=generation,
            deadline_monotonic=deadline_monotonic,
            rows_returned=len(rows),
            db_path=str(db_path or METRICS_DB),
            decision="enrichment_skipped_low_budget",
        )
        for row in rows:
            row.setdefault("arena_rows", 0)
            row.setdefault("missing_evidence", [])
        return rows

    ids = [r["candidate_id"] for r in rows if r.get("candidate_id")]
    if not ids:
        return rows
    placeholders = ",".join("?" for _ in ids)
    arena_counts: dict[str, int] = {}
    if not _past_deadline(deadline_monotonic):
        try:
            arena_rows = conn.execute(
                f"SELECT candidate_id, COUNT(*) AS c FROM arena_results WHERE candidate_id IN ({placeholders}) GROUP BY candidate_id",
                ids,
            ).fetchall()
            arena_counts = {str(r["candidate_id"]): int(r["c"]) for r in arena_rows}
        except sqlite3.OperationalError:
            arena_counts = {}

    score_map: dict[str, dict[str, float]] = {cid: {} for cid in ids}
    if not _past_deadline(deadline_monotonic):
        try:
            score_rows = conn.execute(
                f"SELECT candidate_id, metric, value FROM scores WHERE candidate_id IN ({placeholders})",
                ids,
            ).fetchall()
            for sr in score_rows:
                score_map.setdefault(str(sr["candidate_id"]), {})[str(sr["metric"])] = float(sr["value"] or 0)
        except sqlite3.OperationalError:
            pass

    enriched: list[dict[str, Any]] = []
    for row in rows:
        if _past_deadline(deadline_monotonic):
            record_miner_event(
                step="high_score_miner_partial_result",
                status="partial",
                generation=generation,
                deadline_monotonic=deadline_monotonic,
                rows_returned=len(enriched),
                db_path=str(db_path or METRICS_DB),
                decision=MINER_DEADLINE_EXCEEDED,
            )
            for tail in rows[len(enriched) :]:
                enriched.append({**tail, "arena_rows": 0, "missing_evidence": []})
            return enriched
        cid = str(row.get("candidate_id") or "")
        arena = arena_counts.get(cid, 0)
        metrics = score_map.get(cid, {})
        missing: list[str] = []
        if not arena:
            missing.append("arena")
        if "proof" in str(row.get("rejection_reason") or ""):
            missing.append("proof_density")
        enriched.append(
            {
                **row,
                "arena_rows": arena,
                "missing_evidence": missing,
                "proof_density_score": metrics.get("proof_density_score"),
                "score_replay": metrics.get("score_replay"),
                "bloat_penalty": metrics.get("bloat_penalty"),
                "score_safety": metrics.get("score_safety"),
            }
        )
    return enriched


def mine_high_score_rejections(
    *,
    min_score: float = PROMOTION_THRESHOLD,
    limit: int = 100,
    deadline_monotonic: float | None = None,
    db_path: Path | None = None,
    readonly: bool = False,
    enrich: bool = True,
    generation: int | None = None,
    include_best_ever: bool = False,
) -> dict[str, Any]:
    record_miner_event(
        step="high_score_miner_start",
        status="started",
        generation=generation,
        deadline_monotonic=deadline_monotonic,
        limit=limit,
        db_path=str(db_path or METRICS_DB),
        progress_abort_enabled=deadline_monotonic is not None,
    )

    if _past_deadline(deadline_monotonic):
        result = _empty_result(
            min_score=min_score,
            classification=MINER_DEFERRED_DEADLINE,
            timed_out=True,
            timed_out_stage="before_connect",
            decision=MINER_DEFERRED_DEADLINE,
        )
        record_miner_event(
            step="high_score_miner_deadline_exceeded",
            status="timeout",
            generation=generation,
            deadline_monotonic=deadline_monotonic,
            decision=MINER_DEFERRED_DEADLINE,
        )
        return result

    if _remaining_ms(deadline_monotonic) < DEFAULT_QUERY_BUDGET_MS:
        result = _empty_result(
            min_score=min_score,
            classification=MINER_DEFERRED_DEADLINE,
            timed_out=True,
            timed_out_stage="insufficient_budget",
            decision=MINER_DEFERRED_DEADLINE,
        )
        record_miner_event(
            step="high_score_miner_deadline_exceeded",
            status="deferred",
            generation=generation,
            deadline_monotonic=deadline_monotonic,
            decision=MINER_DEFERRED_DEADLINE,
        )
        return result

    path = db_path or METRICS_DB
    progress_abort = deadline_monotonic is not None
    conn = connect_miner_db(
        db_path=path,
        readonly=readonly,
        deadline_monotonic=deadline_monotonic,
        progress_abort=progress_abort,
    )
    try:
        sql = """
            SELECT candidate_id, parent_id, generation, score_total, rejection_reason,
                   promotion_status, traits, mutation_type, status
            FROM candidates
            WHERE status='rejected' AND score_total >= ?
            ORDER BY score_total DESC
            LIMIT ?
        """
        try:
            raw_rows = _execute_bounded_query(
                conn,
                query_name="top_rejected_by_score",
                sql=sql,
                params=(min_score, int(limit)),
                deadline_monotonic=deadline_monotonic,
                limit=limit,
                generation=generation,
                db_path=path,
                progress_abort_enabled=progress_abort,
            )
        except MinerQueryAborted as exc:
            record_miner_event(
                step="high_score_miner_deadline_exceeded",
                status="timeout",
                generation=generation,
                deadline_monotonic=deadline_monotonic,
                query_name=str(exc),
                decision=MINER_DEADLINE_EXCEEDED,
            )
            return _empty_result(
                min_score=min_score,
                classification=MINER_DEADLINE_EXCEEDED,
                timed_out=True,
                timed_out_stage=str(exc),
                decision=MINER_DEADLINE_EXCEEDED,
            )

        base_rows = [dict(r) for r in raw_rows]
        proof_blocked, closest = _derive_slices(base_rows)
        best_ever: dict[str, Any] = {}
        if include_best_ever and _remaining_ms(deadline_monotonic) >= 2_000:
            try:
                best_rows = _execute_bounded_query(
                    conn,
                    query_name="best_ever_candidate",
                    sql="SELECT candidate_id, score_total, promotion_status FROM candidates ORDER BY score_total DESC LIMIT 1",
                    params=(),
                    deadline_monotonic=deadline_monotonic,
                    limit=1,
                    generation=generation,
                    db_path=path,
                    progress_abort_enabled=progress_abort,
                )
                if best_rows:
                    best_ever = dict(best_rows[0])
            except MinerQueryAborted:
                best_ever = {}

        if enrich and base_rows:
            top_rows = _enrich_rows(
                conn,
                base_rows[:limit],
                deadline_monotonic=deadline_monotonic,
                generation=generation,
                db_path=path,
            )
        else:
            top_rows = base_rows[:limit]
            for row in top_rows:
                row.setdefault("arena_rows", 0)
                row.setdefault("missing_evidence", [])

        result = {
            "min_score": min_score,
            "count_score_gte_threshold": len(base_rows),
            "top_100": top_rows,
            "proof_density_blocked_top_50": proof_blocked,
            "closest_to_promotion_top_25": closest,
            "best_ever": best_ever,
            "timed_out": False,
            "classification": "HIGH_SCORE_MINER_OK",
            "decision": "ok",
        }
        record_miner_event(
            step="high_score_miner_start",
            status="ok",
            generation=generation,
            deadline_monotonic=deadline_monotonic,
            rows_returned=len(top_rows),
            limit=limit,
            db_path=str(path),
            decision="ok",
        )
        return result
    finally:
        try:
            conn.set_progress_handler(None, 0)
        except Exception:
            pass
        conn.close()
