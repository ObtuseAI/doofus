"""CLI: next-cycle seed context builder."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE))

from doofus.evolution.seed_context_builder import build_seed_context
from doofus.reports.cycle_finalizer import write_artifact_pair
from doofus.supervisor.doofus_crash_recovery import load_checkpoint


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--certified-generation", type=int, default=None)
    parser.add_argument("--next-generation", type=int, default=None)
    args = parser.parse_args()
    ck = load_checkpoint()
    certified = args.certified_generation if args.certified_generation is not None else int(ck.get("generation") or 0)
    nxt = args.next_generation if args.next_generation is not None else certified + 1
    payload = build_seed_context(certified_generation=certified, next_generation=nxt)
    out = Path(args.output_dir)
    write_artifact_pair(out, "NEXT_CYCLE_SEED_CONTEXT", payload)
    print(json.dumps({"classification": payload["classification"], "items": len(payload.get("context_items", []))}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
