"""Worker subprocess for shadow upgrade rehearsal."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from doofus.proof.high_score_rescue_loop import run_inline_rescue
from doofus.proof.inline_rescue_budget import SHADOW_UPGRADE_DEFERRED_DEADLINE, SHADOW_UPGRADE_PARTIAL


def main() -> int:
    slow = os.environ.get("DOOFUS_SHADOW_UPGRADE_REHEARSAL_SLOW") == "1"
    if slow:
        import doofus.proof.proof_builder_runner as pbr

        original = pbr.run_process_one_guarded

        def slow_guarded(*args, **kwargs):
            time.sleep(2.0)
            return {"outcome": "proof_partial", "candidate_id": args[0] if args else "unknown"}

        pbr.run_process_one_guarded = slow_guarded

    started = time.monotonic()
    result = run_inline_rescue(baseline=0.72, generation=1640, max_seconds=30, init_phase=True)
    elapsed = time.monotonic() - started
    upgrade = result.get("shadow_upgrade") or {}
    deferred_or_bounded = (
        upgrade.get("deferred") is True
        or upgrade.get("classification") in {SHADOW_UPGRADE_DEFERRED_DEADLINE, SHADOW_UPGRADE_PARTIAL}
        or upgrade.get("processed", 0) <= 1
    )
    print(
        json.dumps(
            {
                "inline_rescue_classification": result.get("classification"),
                "shadow_upgrade": upgrade,
                "shadow_upgrade_deferred_or_bounded": deferred_or_bounded,
                "elapsed_seconds": round(elapsed, 2),
                "timed_out": result.get("timed_out"),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
