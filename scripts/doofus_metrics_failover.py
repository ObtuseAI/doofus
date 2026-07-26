"""Replicate or explicitly promote the configured metrics database replica."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from doofus.runtime.metrics_failover import promote_replica, replicate_metrics_db  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("replicate", "promote"))
    parser.add_argument("--primary", type=Path)
    parser.add_argument("--replica", type=Path)
    parser.add_argument("--authorize", action="store_true", help="required for promote")
    args = parser.parse_args(argv)
    if args.action == "replicate":
        result = replicate_metrics_db(source=args.primary, replica=args.replica)
    else:
        result = promote_replica(primary=args.primary, replica=args.replica, authorize=args.authorize)
    print(json.dumps(result, indent=2))
    return 0 if result["classification"].endswith("COMPLETE") else 2


if __name__ == "__main__":
    raise SystemExit(main())
