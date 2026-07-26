from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from doofus.core.doofus_events import utc_now
from doofus.runtime.isolated_runtime import isolated_runtime_copy
from doofus.safety.on_off_switch import start as switch_start, status as switch_status, stop as switch_stop
from doofus.supervisor.doofus_crash_recovery import load_checkpoint
from doofus.supervisor.doofus_cycle_checkpoint import read_checkpoint
from doofus.supervisor.doofus_loop_runner import run_one_cycle


def _count_live_model_rows(db_path: Path, generation: int) -> int:
    conn = sqlite3.connect(db_path)
    try:
        return int(
            conn.execute(
                "SELECT COUNT(*) FROM model_call_events WHERE generation=? AND classification='DOOFUS_MODEL_LIVE'",
                (generation,),
            ).fetchone()[0]
        )
    finally:
        conn.close()


def _write_report(output_dir: Path, report: dict, *, stem: str = "nonlive_certification_rehearsal") -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / f"{stem}.json").write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )
    md_lines = [
        "# Non-Live Certification Rehearsal",
        "",
        f"- classification: `{report['classification']}`",
        f"- model_classification: `{report.get('model_classification')}`",
        f"- live_model_rows_inserted: `{report.get('live_model_rows_inserted')}`",
        f"- checkpoint_promoted: `{report.get('checkpoint_promoted')}`",
        f"- cycle_checkpoint_promoted: `{report.get('cycle_checkpoint_promoted')}`",
    ]
    (output_dir / f"{stem}.md").write_text("\n".join(md_lines) + "\n", encoding="utf-8")


def run_rehearsal(*, output_dir: Path, stem: str = "nonlive_certification_rehearsal") -> dict:
    with isolated_runtime_copy(clear_stop_flags=False) as iso:
        import doofus.supervisor.doofus_loop_runner as loop_runner

        checkpoint_before = load_checkpoint()
        cycle_before = read_checkpoint()
        checkpoint_file_before = json.loads((iso.state / "last_checkpoint.json").read_text(encoding="utf-8"))
        cycle_file_before = json.loads((iso.state / "cycle_checkpoint.json").read_text(encoding="utf-8"))
        live_rows_before = _count_live_model_rows(iso.metrics_db, 1638)
        stop_before = switch_status()

        shadow_checkpoint = dict(checkpoint_before)
        shadow_cycle = dict(cycle_before)
        cycle_events: list[dict] = []

        old_load_checkpoint = loop_runner.load_checkpoint
        old_finalize_checkpoint = loop_runner.finalize_checkpoint
        old_save_checkpoint = loop_runner.save_checkpoint
        old_write_checkpoint = loop_runner.write_checkpoint

        def fake_load_checkpoint() -> dict:
            return dict(shadow_checkpoint)

        def fake_finalize_checkpoint(*, generation: int, baseline_score: float, run_id: str, phase: str, **extra) -> dict:
            shadow_checkpoint.update(
                {
                    "generation": generation,
                    "baseline_score": baseline_score,
                    "run_id": run_id,
                    "phase": phase,
                    "saved_at": utc_now(),
                    **extra,
                }
            )
            return dict(shadow_checkpoint)

        def fake_save_checkpoint(payload: dict) -> dict:
            shadow_checkpoint.update(payload)
            shadow_checkpoint["saved_at"] = utc_now()
            return dict(shadow_checkpoint)

        def fake_write_checkpoint(stage: str, data: dict) -> dict:
            nonlocal shadow_cycle
            row = {"stage": stage, "data": dict(data), "saved_at": utc_now()}
            cycle_events.append(row)
            shadow_cycle = row
            return row

        loop_runner.load_checkpoint = fake_load_checkpoint
        loop_runner.finalize_checkpoint = fake_finalize_checkpoint
        loop_runner.save_checkpoint = fake_save_checkpoint
        loop_runner.write_checkpoint = fake_write_checkpoint
        try:
            switch_start()
            try:
                result = run_one_cycle(dry_run=False, live_model_if_available=False)
            finally:
                switch_stop()
        finally:
            loop_runner.load_checkpoint = old_load_checkpoint
            loop_runner.finalize_checkpoint = old_finalize_checkpoint
            loop_runner.save_checkpoint = old_save_checkpoint
            loop_runner.write_checkpoint = old_write_checkpoint

        live_rows_after = _count_live_model_rows(iso.metrics_db, 1638)
        checkpoint_file_after = json.loads((iso.state / "last_checkpoint.json").read_text(encoding="utf-8"))
        cycle_file_after = json.loads((iso.state / "cycle_checkpoint.json").read_text(encoding="utf-8"))

        report = {
            "classification": "DOOFUS_NONLIVE_CERTIFICATION_REHEARSAL",
            "isolated_root": str(iso.root),
            "model_classification": result.get("model_result", {}).get("classification"),
            "cycle_classification": result.get("classification"),
            "inline_rescue_classification": result.get("inline_rescue", {}).get("classification"),
            "live_model_rows_inserted": live_rows_after - live_rows_before,
            "checkpoint_promoted": checkpoint_file_after.get("generation") != checkpoint_file_before.get("generation"),
            "cycle_checkpoint_promoted": cycle_file_after.get("data", {}).get("generation") != cycle_file_before.get("data", {}).get("generation"),
            "stop_requested_before": stop_before.get("stop_requested"),
            "stop_requested_after": switch_status().get("stop_requested"),
            "checkpoint_file_before": checkpoint_file_before,
            "checkpoint_file_after": checkpoint_file_after,
            "cycle_checkpoint_file_before": cycle_file_before,
            "cycle_checkpoint_file_after": cycle_file_after,
            "shadow_checkpoint_after": shadow_checkpoint,
            "shadow_cycle_after": shadow_cycle,
            "cycle_events": cycle_events[-20:],
            "result": result,
        }

    _write_report(output_dir, report, stem=stem)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a non-live isolated certification rehearsal.")
    parser.add_argument(
        "--output-dir",
        default=str(WORKSPACE / "artifacts" / "doofus" / "gen1637-postlive-certification-v1"),
    )
    args = parser.parse_args()
    output_dir = Path(args.output_dir)

    report = run_rehearsal(output_dir=output_dir)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
