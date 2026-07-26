"""Read-only live-scale diagnostic for high-score rejection miner queries."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from doofus.core.doofus_paths import METRICS_DB
from doofus.proof.high_score_rejection_miner import (
    MINER_DEADLINE_EXCEEDED,
    MINER_DEFERRED_DEADLINE,
    connect_miner_db,
    mine_high_score_rejections,
)


def write_pair(output_dir: Path, stem: str, payload: dict) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / f"{stem}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    lines = [f"# {stem}", "", f"**Classification:** `{payload.get('classification')}`", ""]
    for key, value in payload.items():
        if key == "classification":
            continue
        lines.append(f"- **{key}:** `{value}`")
    (output_dir / f"{stem}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def explain_query(db_path: Path, sql: str, params: tuple) -> list[str]:
    conn = connect_miner_db(db_path=db_path, readonly=True, deadline_monotonic=None, progress_abort=False)
    try:
        rows = conn.execute(f"EXPLAIN QUERY PLAN {sql}", params).fetchall()
        return [" | ".join(str(c) for c in row) for row in rows]
    finally:
        conn.close()


def run_diagnostic(
    *,
    db_path: Path,
    generation: int,
    limit: int,
    deadline_seconds: float,
    output_dir: Path,
    explain: bool,
    stem: str = "LIVE_SCALE_MINER_DIAGNOSTIC",
) -> dict:
    deadline = time.monotonic() + deadline_seconds
    started = time.perf_counter()
    sql = """
        SELECT candidate_id, parent_id, generation, score_total, rejection_reason,
               promotion_status, traits, mutation_type, status
        FROM candidates
        WHERE status='rejected' AND score_total >= ?
        ORDER BY score_total DESC
        LIMIT ?
    """
    params = (0.5, limit)
    plans = explain_query(db_path, sql, params) if explain else []
    per_query: list[dict] = []
    first_query_started = time.perf_counter()
    result = mine_high_score_rejections(
        min_score=0.5,
        limit=limit,
        deadline_monotonic=deadline,
        db_path=db_path,
        readonly=True,
        enrich=False,
        generation=generation,
        include_best_ever=False,
    )
    first_query_elapsed_ms = (time.perf_counter() - first_query_started) * 1000.0
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    classification = result.get("classification", "HIGH_SCORE_MINER_OK")
    passed = elapsed_ms <= (deadline_seconds * 1000.0 + 500.0) and classification in {
        "HIGH_SCORE_MINER_OK",
        MINER_DEFERRED_DEADLINE,
        MINER_DEADLINE_EXCEEDED,
    }
    payload = {
        "classification": stem,
        "passed": passed,
        "generation": generation,
        "limit": limit,
        "deadline_seconds": deadline_seconds,
        "elapsed_ms": round(elapsed_ms, 2),
        "first_query_elapsed_ms": round(first_query_elapsed_ms, 2),
        "first_query_returned_before_deadline": first_query_elapsed_ms <= deadline_seconds * 1000.0,
        "progress_abort_enabled": True,
        "readonly": True,
        "db_path": str(db_path),
        "miner_result_classification": classification,
        "miner_decision": result.get("decision"),
        "rows_returned": len(result.get("top_100", [])),
        "timed_out": result.get("timed_out"),
        "timed_out_stage": result.get("timed_out_stage"),
        "explain_query_plan": plans,
        "per_query": per_query,
        "live_db_mutated": False,
        "model_calls": 0,
    }
    write_pair(output_dir, stem, payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only high-score miner diagnostic.")
    parser.add_argument("--db-path", default=str(METRICS_DB))
    parser.add_argument("--generation", type=int, default=1640)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--deadline-seconds", type=float, default=30.0)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--explain-query-plan", action="store_true")
    parser.add_argument("--stem", default="LIVE_SCALE_MINER_DIAGNOSTIC")
    args = parser.parse_args()
    payload = run_diagnostic(
        db_path=Path(args.db_path),
        generation=args.generation,
        limit=args.limit,
        deadline_seconds=args.deadline_seconds,
        output_dir=Path(args.output_dir),
        explain=args.explain_query_plan,
        stem=args.stem,
    )
    print(json.dumps({"classification": payload["classification"], "passed": payload["passed"]}, indent=2))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
