"""One-shot evolution run against a registered external project.

Examples:
  python scripts/doofus_evolve_project.py myproj                    # measure-only per flags
  python scripts/doofus_evolve_project.py myproj --generations 10 --apply
  python scripts/doofus_evolve_project.py myproj --target threshold --measure-only

The adaptive hill-climber remembers step size, direction, and best-ever fitness
per target in runtime/state/codeevolve/projects/<id>/evolve_state.json, so
repeated runs keep making progress. --apply grants this run permission to write
accepted param changes into the project (still snapshot + rollback guarded);
without it, the run honors the project's auto_apply flag and
DOOFUS_CODEEVOLVE_AUTO_APPLY.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from doofus.meta.codeevolve.external_evolver import evolve_project  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run hill-climbing generations against one external project.")
    ap.add_argument("project_id", help="Registered project id (see doofus_register_project.py --list)")
    ap.add_argument("--generations", type=int, default=5, help="Generations to run (default 5)")
    ap.add_argument("--target", help="Only evolve this target id")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="Allow accepted changes to be written this run")
    mode.add_argument("--measure-only", action="store_true", help="Force measure-only this run")
    args = ap.parse_args(argv)

    apply_override = True if args.apply else (False if args.measure_only else None)
    result = evolve_project(
        args.project_id,
        generations=args.generations,
        target_filter=args.target,
        apply_override=apply_override,
    )
    for r in result.get("results", []):
        print(json.dumps({k: r.get(k) for k in ("target", "classification", "fitness", "accepted", "summary")}))
    summary = {k: v for k, v in result.items() if k != "results"}
    print(json.dumps(summary, indent=2, default=str))
    return 0 if result["classification"] == "EVOLVE_PROJECT_COMPLETE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
