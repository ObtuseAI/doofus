from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from doofus.runtime.live_db_preflight import inspect_live_db, scrub_live_db, write_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Doofus live DB contamination preflight.")
    parser.add_argument("--checkpoint-generation", type=int, default=None)
    parser.add_argument("--target-generation", type=int, default=None)
    parser.add_argument(
        "--output-dir",
        default=str(WORKSPACE / "artifacts" / "doofus" / "live-db-preflight"),
    )
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--backup-only", action="store_true")
    parser.add_argument("--scrub-target-generation", action="store_true")
    parser.add_argument("--scrub-above-checkpoint", action="store_true")
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args()

    mode_flags = [
        bool(args.backup_only),
        bool(args.scrub_target_generation),
        bool(args.scrub_above_checkpoint),
    ]
    if sum(mode_flags) > 1:
        raise SystemExit("choose only one of --backup-only, --scrub-target-generation, --scrub-above-checkpoint")

    output_dir = Path(args.output_dir)
    report = inspect_live_db(
        checkpoint_generation=args.checkpoint_generation,
        target_generation=args.target_generation,
    )
    print(f"DB path: {report['db_path']}", flush=True)

    if args.backup_only:
        from doofus.runtime.live_db_preflight import backup_live_db

        backup_path = backup_live_db(output_dir=output_dir, label="backup_only")
        report = {
            **report,
            "classification": "DOOFUS_LIVE_DB_PREFLIGHT_BACKUP_ONLY",
            "backup_path": str(backup_path),
        }
        stem = "live_db_preflight_backup_only"
    elif args.scrub_target_generation:
        report = scrub_live_db(
            mode="scrub_target_generation",
            confirm=args.confirm,
            output_dir=output_dir,
            checkpoint_generation=args.checkpoint_generation,
            target_generation=args.target_generation,
        )
        stem = "live_db_preflight_scrub_target_generation"
    elif args.scrub_above_checkpoint:
        report = scrub_live_db(
            mode="scrub_above_checkpoint",
            confirm=args.confirm,
            output_dir=output_dir,
            checkpoint_generation=args.checkpoint_generation,
            target_generation=args.target_generation,
        )
        stem = "live_db_preflight_scrub_above_checkpoint"
    else:
        report["classification"] = "DOOFUS_LIVE_DB_PREFLIGHT_CHECK_ONLY"
        stem = "live_db_preflight_check_only"

    json_path, md_path = write_report(report=report, output_dir=output_dir, stem=stem)
    print(json.dumps(report, indent=2))
    print(json_path)
    print(md_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
