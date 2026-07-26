"""Compact Doofus generation summary - read-only, no live route."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

WORKSPACE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE))

from doofus.core.doofus_paths import METRICS_DB, STATE
from doofus.supervisor.doofus_crash_recovery import load_checkpoint
from doofus.supervisor.doofus_cycle_checkpoint import read_checkpoint
from doofus.safety.on_off_switch import status


def _read_jsonl_tail(path: Path, limit: int = 500) -> list[dict]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    rows = []
    for line in lines[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return rows


def _db_generation_counts(generation: int) -> dict[str, Any]:
    if not METRICS_DB.exists():
        return {"error": "db_missing"}
    conn = sqlite3.connect(f"file:{METRICS_DB}?mode=ro", uri=True, timeout=5.0)
    counts: dict[str, int] = {}
    for table in ("candidates", "cycles", "model_call_events", "map_elites_cells"):
        try:
            row = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE generation=?",
                (generation,),
            ).fetchone()
            counts[table] = int(row[0]) if row else 0
        except sqlite3.Error:
            counts[table] = -1
    try:
        row = conn.execute("SELECT MAX(generation) FROM candidates").fetchone()
        counts["candidates_max_generation"] = int(row[0]) if row and row[0] is not None else None
    except sqlite3.Error:
        counts["candidates_max_generation"] = None
    conn.close()
    return counts


def build_generation_summary(generation: int) -> dict[str, Any]:
    ck = load_checkpoint()
    cc = read_checkpoint()
    stop = status()
    db_counts = _db_generation_counts(generation)

    inline_events = _read_jsonl_tail(STATE / "inline_rescue_events.jsonl")
    gen_inline = [e for e in inline_events if e.get("generation") == generation]
    proof_events = _read_jsonl_tail(STATE / "proof_builder_queue_events.jsonl")
    gen_proof = [e for e in proof_events if e.get("generation") == generation]

    scoring_events = _read_jsonl_tail(STATE / "scoring_step_events.jsonl")
    gen_scoring = [e for e in scoring_events if e.get("generation") == generation]
    max_scoring_ms = max((float(e.get("duration_ms") or 0) for e in gen_scoring), default=0.0)

    proof_queue_path = STATE / "proof_builder_queue.json"
    proof_queue_size = 0
    if proof_queue_path.exists():
        try:
            proof_queue_size = len(json.loads(proof_queue_path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            pass

    inline_summary = {
        "event_count": len(gen_inline),
        "timeout_count": sum(1 for e in gen_inline if e.get("event_type") == "timeout"),
        "skip_count": sum(1 for e in gen_inline if e.get("status") == "skipped"),
        "last_classification": gen_inline[-1].get("detail", {}).get("classification") if gen_inline else None,
    }

    return {
        "classification": "DOOFUS_GENERATION_SUMMARY",
        "generation": generation,
        "checkpoint": ck,
        "cycle_checkpoint": cc,
        "stop_flag": stop,
        "db_path": str(METRICS_DB),
        "db_generation_counts": db_counts,
        "model_call_events_count": db_counts.get("model_call_events", 0),
        "candidates_count": db_counts.get("candidates", 0),
        "cycles_count": db_counts.get("cycles", 0),
        "inline_rescue": inline_summary,
        "proof_builder_queue_size": proof_queue_size,
        "proof_builder_events_count": len(gen_proof),
        "scoring_events_count": len(gen_scoring),
        "max_scoring_step_ms": round(max_scoring_ms, 2),
        "live_route_invoked": False,
    }


def write_pair(out_dir: Path, stem: str, payload: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{stem}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    lines = [f"# Generation {payload.get('generation', '?')} Summary", ""]
    for k, v in payload.items():
        if isinstance(v, (dict, list)):
            lines.extend([f"## {k}", "", "```json", json.dumps(v, indent=2)[:6000], "```", ""])
        else:
            lines.append(f"- **{k}**: `{v}`")
    (out_dir / f"{stem}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Doofus generation summary (read-only).")
    parser.add_argument("--generation", type=int, default=1639)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    summary = build_generation_summary(args.generation)
    stem = f"generation_{args.generation}_summary"
    write_pair(args.output_dir, stem, summary)
    print(json.dumps({"classification": summary["classification"], "generation": args.generation}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
