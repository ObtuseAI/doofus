# -*- coding: utf-8 -*-
"""Wait for a checkpoint generation/phase condition."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    from doofus.supervisor.doofus_crash_recovery import load_checkpoint

    parser = argparse.ArgumentParser()
    parser.add_argument("--generation-at-least", type=int, required=True)
    parser.add_argument("--phase", default="complete")
    parser.add_argument("--timeout-seconds", type=float, default=240.0)
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    args = parser.parse_args()

    deadline = time.time() + float(args.timeout_seconds)
    latest = load_checkpoint()
    while time.time() < deadline:
        latest = load_checkpoint()
        if int(latest.get("generation") or 0) >= args.generation_at_least and str(latest.get("phase") or "") == args.phase:
            print(json.dumps({"matched": True, "checkpoint": latest}, indent=2))
            return 0
        time.sleep(max(0.25, float(args.poll_seconds)))
    print(json.dumps({"matched": False, "checkpoint": latest, "generation_at_least": args.generation_at_least, "phase": args.phase}, indent=2))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
