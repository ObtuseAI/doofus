"""Worker for isolated inline rescue rehearsal."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE))

from doofus.core import doofus_paths
from doofus.proof.high_score_rescue_loop import run_inline_rescue


def main() -> int:
    slow_ms = int(os.environ.get("DOOFUS_MINER_REHEARSAL_SLOW_MS", "0"))
    if slow_ms > 0:
        import doofus.proof.high_score_rejection_miner as miner

        original = miner._execute_bounded_query

        def slow_query(conn, **kwargs):
            time.sleep(slow_ms / 1000.0)
            return original(conn, **kwargs)

        miner._execute_bounded_query = slow_query

    started = time.monotonic()
    result = run_inline_rescue(baseline=0.9, generation=1640, max_seconds=10)
    elapsed = time.monotonic() - started
    conn = __import__("sqlite3").connect(doofus_paths.METRICS_DB)
    gen1640 = conn.execute("SELECT COUNT(*) FROM candidates WHERE generation=1640").fetchone()[0]
    conn.close()
    print(
        json.dumps(
            {
                "classification": result.get("classification"),
                "timed_out": result.get("timed_out"),
                "elapsed_seconds": round(elapsed, 2),
                "gen1640_rows_in_temp_db": gen1640,
                "mined": result.get("mined"),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
