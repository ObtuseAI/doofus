from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from doofus.arenas.arena_router import reset_cycle_budget
from doofus.config.proof_builder_runtime_config import bootstrap_autonomous_runtime
from doofus.core.metrics_db import connect_metrics_db
from doofus.evolution.evolution_pressure_mode import filter_retired_parents
from doofus.mutation.candidate_generator import generate_cycle_candidates
from doofus.runtime.isolated_runtime import isolated_runtime_copy
from doofus.scoring.scoring_telemetry import (
    bind_candidate,
    bind_cycle,
    record_progress as record_scoring_progress,
    record_scoring_event,
    record_timeout,
    reset_candidate,
    reset_cycle,
    reset_events_file,
)
from doofus.supervisor.doofus_crash_recovery import load_checkpoint
from doofus.supervisor.doofus_loop_runner import _score_one_candidate
from doofus.supervisor.metrics_writer import log_mutation, upsert_candidate

REPORTS = WORKSPACE / "runtime" / "reports"


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def _candidate_top(rows: list[dict], limit: int = 5) -> list[dict]:
    items = [
        {
            "candidate_id": row.get("candidate_id"),
            "duration_ms": row.get("duration_ms"),
            "candidate_index": row.get("candidate_index"),
        }
        for row in rows
        if row.get("scorer_name") == "candidate_scoring"
        and row.get("substep") == "candidate_total"
        and row.get("event_type") in {"end", "cached", "timeout", "error"}
        and row.get("candidate_id")
    ]
    items.sort(key=lambda item: float(item.get("duration_ms") or 0), reverse=True)
    return items[:limit]


def _scorer_totals(rows: list[dict]) -> list[dict]:
    totals: dict[tuple[str, str], dict] = {}
    for row in rows:
        if row.get("event_type") not in {"end", "cached", "timeout", "error"}:
            continue
        key = (row.get("scorer_name") or "", row.get("substep") or "")
        item = totals.setdefault(
            key,
            {
                "scorer_name": row.get("scorer_name"),
                "substep": row.get("substep"),
                "duration_ms_total": 0.0,
                "calls": 0,
                "cache_hits": 0,
                "sqlite_write_count": 0,
                "artifact_write_count": 0,
            },
        )
        item["duration_ms_total"] += float(row.get("duration_ms") or 0.0)
        item["calls"] += 1
        item["cache_hits"] += 1 if row.get("cache_hit") else 0
        item["sqlite_write_count"] += int(row.get("sqlite_write_count") or 0)
        item["artifact_write_count"] += int(row.get("artifact_write_count") or 0)
    out = list(totals.values())
    out.sort(key=lambda item: item["duration_ms_total"], reverse=True)
    return out


def _cache_summary(rows: list[dict]) -> list[dict]:
    stats: dict[str, dict] = defaultdict(lambda: {"events": 0, "cache_hits": 0})
    for row in rows:
        scorer = row.get("scorer_name") or "unknown"
        stats[scorer]["events"] += 1
        stats[scorer]["cache_hits"] += 1 if row.get("cache_hit") else 0
    out = []
    for scorer, item in stats.items():
        out.append(
            {
                "scorer_name": scorer,
                "events": item["events"],
                "cache_hits": item["cache_hits"],
                "cache_misses": max(item["events"] - item["cache_hits"], 0),
            }
        )
    out.sort(key=lambda item: item["cache_hits"], reverse=True)
    return out


def _write_summary_markdown(path: Path, report: dict) -> None:
    lines = [
        "# Doofus Gen1637 Scoring Diagnostic",
        "",
        f"- status: `{report['diagnostic_status']}`",
        f"- candidate workload: `{report['candidate_count']}`",
        f"- candidate source: `{report['candidate_source']}`",
        f"- scoring wall time seconds: `{report['scoring_wall_time_seconds']}`",
        f"- slowest scorer: `{report['slowest_scorer']}`",
        f"- slowest candidate: `{report['slowest_candidate']}`",
        "",
        "## Top Scorers",
    ]
    for item in report["per_scorer_timing"][:8]:
        lines.append(
            f"- `{item['scorer_name']}::{item['substep']}` total_ms={round(item['duration_ms_total'], 2)} calls={item['calls']} cache_hits={item['cache_hits']}"
        )
    lines.append("")
    lines.append("## Slowest Candidates")
    for item in report["slowest_candidates"]:
        lines.append(
            f"- `{item['candidate_id']}` idx={item['candidate_index']} duration_ms={round(float(item['duration_ms'] or 0), 2)}"
        )
    lines.append("")
    lines.append("## Safe Degradation Recommendations")
    for rec in report["safe_degradation_recommendations"]:
        lines.append(f"- {rec}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _seed_parent_rows(*, parent_ids: set[str], isolated_db: Path) -> int:
    parent_ids = {pid for pid in parent_ids if pid}
    if not parent_ids:
        return 0
    live_db = WORKSPACE / "runtime" / "state" / "doofus_metrics.sqlite"
    live_conn = sqlite3.connect(f"file:{live_db}?mode=ro", uri=True, timeout=2.0)
    iso_conn = connect_metrics_db(db_path=isolated_db)
    seeded = 0
    try:
        placeholders = ",".join("?" for _ in parent_ids)
        rows = live_conn.execute(
            f"""
            SELECT candidate_id, parent_id, generation, traits, mutation_type, arena_targets, status,
                   score_total, score_safety, score_replay, score_generalization,
                   score_compounding, score_recursive_learning, rejection_reason, promotion_status, created_at
            FROM candidates
            WHERE candidate_id IN ({placeholders})
            """,
            tuple(parent_ids),
        ).fetchall()
        for row in rows:
            iso_conn.execute(
                """INSERT OR REPLACE INTO candidates VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                row,
            )
            seeded += 1
        iso_conn.commit()
    finally:
        live_conn.close()
        iso_conn.close()
    return seeded


def main() -> int:
    parser = argparse.ArgumentParser(description="Run isolated Doofus scoring diagnostic.")
    parser.add_argument("--candidate-count", type=int, default=24)
    parser.add_argument("--from-certified-baseline", type=int, required=True)
    parser.add_argument("--isolated-runtime", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=480)
    parser.add_argument("--no-promotion", action="store_true")
    args = parser.parse_args()

    REPORTS.mkdir(parents=True, exist_ok=True)
    report_json = REPORTS / "doofus_gen1637_scoring_diagnostic_report.json"
    report_md = REPORTS / "doofus_gen1637_scoring_diagnostic_report.md"
    events_copy = REPORTS / "doofus_gen1637_scoring_step_events_diagnostic.jsonl"

    bootstrap_autonomous_runtime()
    print("diagnostic: bootstrap complete", flush=True)

    if not args.isolated_runtime:
        raise SystemExit("--isolated-runtime is required for this diagnostic")

    with isolated_runtime_copy(source_root=WORKSPACE, clear_stop_flags=True) as iso:
        print(f"diagnostic: isolated runtime ready at {iso.root}", flush=True)
        reset_events_file()
        reset_cycle_budget()

        checkpoint = load_checkpoint()
        if int(checkpoint.get("generation", -1)) != args.from_certified_baseline:
            raise SystemExit(
                f"isolated checkpoint generation mismatch: expected {args.from_certified_baseline}, got {checkpoint.get('generation')}"
            )

        generation = args.from_certified_baseline + 1
        baseline = float(checkpoint.get("baseline_score", 0.5))
        candidates = filter_retired_parents(
            generate_cycle_candidates(generation, count=args.candidate_count)
        )
        print(f"diagnostic: generated {len(candidates)} candidates for generation {generation}", flush=True)
        seeded_parent_rows = _seed_parent_rows(
            parent_ids={c.get("parent_id") for c in candidates if c.get("parent_id")},
            isolated_db=iso.metrics_db,
        )
        print(f"diagnostic: seeded {seeded_parent_rows} parent rows into isolated metrics db", flush=True)
        candidate_source = "generated_from_certified_baseline"
        scoring_started = time.perf_counter()
        promoted = shadow = rejected = 0
        timed_out = False
        timed_out_candidate_id = ""
        timed_out_candidate_index = None
        scored: list[dict] = []

        cycle_token = bind_cycle(
            generation=generation,
            cycle_id=f"diagnostic-{generation}",
            candidate_count=len(candidates),
            batch_id="diagnostic_scoring",
        )
        record_scoring_event(
            scorer_name="diagnostic_scoring",
            scorer_module="scripts.doofus_scoring_diagnostic",
            substep="diagnostic_loop",
            event_type="start",
            candidate_count=len(candidates),
        )

        conn = connect_metrics_db(db_path=iso.metrics_db)
        try:
            for idx, candidate in enumerate(candidates, start=1):
                print(f"diagnostic: scoring candidate {idx}/{len(candidates)} {candidate['candidate_id']}", flush=True)
                elapsed = time.perf_counter() - scoring_started
                if elapsed > args.timeout_seconds:
                    timed_out = True
                    timed_out_candidate_id = candidate.get("candidate_id", "")
                    timed_out_candidate_index = idx
                    record_timeout(
                        error_type="DiagnosticTimeout",
                        error_message_sanitized=f"diagnostic scoring exceeded {args.timeout_seconds}s before candidate {idx}",
                    )
                    break

                candidate_token = bind_candidate(
                    candidate_id=candidate["candidate_id"],
                    candidate_index=idx,
                    candidate_count=len(candidates),
                )
                traits_before = list(candidate.get("traits") or [])
                if candidate.get("parent_id"):
                    log_mutation(conn, candidate["candidate_id"], candidate.get("mutation_type", "trait_mutation"))
                try:
                    candidate, promo, p_d, s_d, r_d, baseline = _score_one_candidate(
                        conn,
                        candidate,
                        generation=generation,
                        baseline=baseline,
                        dry_run=False,
                        traits_before=traits_before,
                    )
                    promoted += p_d
                    shadow += s_d
                    rejected += r_d
                    scored.append(candidate)
                    if args.no_promotion and promo.get("promoted"):
                        candidate["status"] = "promoted_isolated_diagnostic_only"
                except Exception as exc:
                    rejected += 1
                    candidate["status"] = "error"
                    candidate["rejection_reason"] = f"pipeline_error:{type(exc).__name__}"
                    upsert_candidate(conn, candidate, {"score_total": 0}, {"promotion_status": "rejected"})
                    scored.append(candidate)
                finally:
                    heartbeat_progress = idx < len(candidates)
                    record_scoring_progress(
                        scorer_name="diagnostic_scoring",
                        scorer_module="scripts.doofus_scoring_diagnostic",
                        substep="candidate_progress",
                        heartbeat_written=heartbeat_progress,
                        input_size=idx,
                        output_size=len(candidates),
                    )
                    reset_candidate(candidate_token)
            conn.commit()
            record_scoring_event(
                scorer_name="diagnostic_scoring",
                scorer_module="scripts.doofus_scoring_diagnostic",
                substep="diagnostic_loop",
                event_type="timeout" if timed_out else "end",
                duration_ms=(time.perf_counter() - scoring_started) * 1000.0,
                candidate_count=len(candidates),
                output_size=len(scored),
                status="timeout" if timed_out else "ok",
                error_type="DiagnosticTimeout" if timed_out else "",
                error_message_sanitized=(
                    f"timeout before candidate {timed_out_candidate_index}" if timed_out else ""
                ),
            )
        finally:
            conn.close()
            reset_cycle(cycle_token)

        if iso.state.joinpath("scoring_step_events.jsonl").exists():
            shutil.copy2(iso.state / "scoring_step_events.jsonl", events_copy)

        rows = _read_jsonl(iso.state / "scoring_step_events.jsonl")
        scorers = _scorer_totals(rows)
        slowest_candidates = _candidate_top(rows)
        cache_summary = _cache_summary(rows)

        total_seconds = round(time.perf_counter() - scoring_started, 2)
        slowest_scorer = ""
        if scorers:
            slowest_scorer = f"{scorers[0]['scorer_name']}::{scorers[0]['substep']}"
        slowest_candidate = slowest_candidates[0]["candidate_id"] if slowest_candidates else ""

        recommendations: list[str] = []
        if scorers and scorers[0]["scorer_name"] == "arena_scoring":
            recommendations.append(
                "Use cheap score gating before live arena evaluation, and reserve live agent_arcade work for top-K promotion-eligible candidates."
            )
        if any(item["scorer_name"] == "proof_density" for item in scorers[:4]):
            recommendations.append(
                "Reuse the first candidate scorecard inside promotion evaluation instead of recomputing proof density and lineage work."
            )
        if any(item["sqlite_write_count"] > 0 or item["artifact_write_count"] > 0 for item in scorers[:6]):
            recommendations.append(
                "Batch or defer non-promotion-critical SQLite and artifact writes such as MAP-Elites and telemetry persistence."
            )
        if not recommendations:
            recommendations.append(
                "Keep scorer-level telemetry enabled and apply the slowest-scorer-specific fix from the timing table before the next live attempt."
            )

        report = {
            "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "workspace": str(WORKSPACE),
            "diagnostic_status": "PASS_WITH_NOTES" if timed_out else "PASS",
            "candidate_count": len(candidates),
            "candidate_source": candidate_source,
            "from_certified_baseline": args.from_certified_baseline,
            "isolated_runtime_root": str(iso.root),
            "isolated_runtime_state": str(iso.state),
            "isolated_events_jsonl_copy": str(events_copy) if events_copy.exists() else "",
            "seeded_parent_rows": seeded_parent_rows,
            "scoring_wall_time_seconds": total_seconds,
            "timed_out": timed_out,
            "timed_out_candidate_id": timed_out_candidate_id,
            "timed_out_candidate_index": timed_out_candidate_index,
            "promoted_count": promoted,
            "shadow_promoted_count": shadow,
            "rejected_count": rejected,
            "slowest_scorer": slowest_scorer,
            "slowest_candidate": slowest_candidate,
            "per_scorer_timing": scorers,
            "slowest_candidates": slowest_candidates,
            "cache_hit_miss_table": cache_summary,
            "sqlite_artifact_write_timing": [
                {
                    "scorer_name": item["scorer_name"],
                    "substep": item["substep"],
                    "sqlite_write_count": item["sqlite_write_count"],
                    "artifact_write_count": item["artifact_write_count"],
                    "duration_ms_total": round(item["duration_ms_total"], 2),
                }
                for item in scorers
                if item["sqlite_write_count"] or item["artifact_write_count"]
            ],
            "safe_degradation_recommendations": recommendations,
        }
        report_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
        _write_summary_markdown(report_md, report)

    print(json.dumps(report, indent=2))
    print(report_json)
    print(report_md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
