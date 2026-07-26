from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from doofus.runtime.live_db_preflight import inspect_live_db
from scripts.doofus_nonlive_certification_rehearsal import run_rehearsal


def _write_report(output_dir: Path, report: dict) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "gen1638_nonlive_readiness_rehearsal.json").write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )
    md_lines = [
        "# Gen1638 Non-Live Readiness Rehearsal",
        "",
        f"- classification: `{report['classification']}`",
        f"- readiness_passed: `{report['readiness_passed']}`",
        f"- model_classification: `{report['rehearsal'].get('model_classification')}`",
        f"- live_model_rows_inserted: `{report['rehearsal'].get('live_model_rows_inserted')}`",
        f"- checkpoint_promoted: `{report['rehearsal'].get('checkpoint_promoted')}`",
        f"- cycle_checkpoint_promoted: `{report['rehearsal'].get('cycle_checkpoint_promoted')}`",
        f"- stop_requested_after: `{report['rehearsal'].get('stop_requested_after')}`",
        f"- live_db_clean_before: `{not report['preflight_before'].get('contamination_detected')}`",
        f"- live_db_clean_after: `{not report['preflight_after'].get('contamination_detected')}`",
    ]
    (output_dir / "gen1638_nonlive_readiness_rehearsal.md").write_text(
        "\n".join(md_lines) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a safe non-live gen1638 readiness rehearsal.")
    parser.add_argument(
        "--output-dir",
        default=str(WORKSPACE / "artifacts" / "doofus" / "gen1637-clean-commit-gen1638-readiness-v1"),
    )
    parser.add_argument("--live", action="store_true", help="Refused: this rehearsal is dry-run only.")
    args = parser.parse_args()
    if args.live:
        raise SystemExit("--live is refused; this rehearsal is dry-run only")

    output_dir = Path(args.output_dir)
    preflight_before = inspect_live_db(target_generation=1638)
    if preflight_before.get("contamination_detected"):
        report = {
            "classification": "DOOFUS_GEN1638_NONLIVE_READINESS_REFUSED",
            "reason": "live_db_contamination_detected_before_rehearsal",
            "preflight_before": preflight_before,
        }
        _write_report(output_dir, {**report, "readiness_passed": False, "rehearsal": {}})
        print(json.dumps(report, indent=2))
        return 1

    rehearsal = run_rehearsal(output_dir=output_dir, stem="nonlive_certification_rehearsal")
    preflight_after = inspect_live_db(target_generation=1638)
    readiness_passed = all([
        rehearsal.get("model_classification") == "DOOFUS_MODEL_DRY_RUN",
        rehearsal.get("live_model_rows_inserted") == 0,
        rehearsal.get("checkpoint_promoted") is False,
        rehearsal.get("cycle_checkpoint_promoted") is False,
        rehearsal.get("stop_requested_after") is True,
        preflight_after.get("db_max_generation") == 1637,
        preflight_after.get("target_generation_total") == 0,
        rehearsal.get("cycle_classification") == "DOOFUS_CYCLE_COMPLETE",
    ])
    report = {
        "classification": "DOOFUS_GEN1638_NONLIVE_READINESS_REHEARSAL",
        "readiness_passed": readiness_passed,
        "preflight_before": preflight_before,
        "rehearsal": rehearsal,
        "preflight_after": preflight_after,
    }
    _write_report(output_dir, report)
    print(json.dumps(report, indent=2))
    return 0 if readiness_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
