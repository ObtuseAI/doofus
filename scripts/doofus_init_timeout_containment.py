"""Init timeout containment helper - backup-first partial row detection and baseline restore."""
from __future__ import annotations

import json
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from doofus.core.doofus_paths import STATE
from doofus.runtime.live_db_preflight import backup_live_db, inspect_live_db
from doofus.safety.on_off_switch import status, stop
from doofus.supervisor.checkpoint_baseline import (
    CheckpointSchemaError,
    backup_checkpoint_files,
    extract_checkpoint,
    extract_cycle_checkpoint,
    validate_checkpoint,
)
from doofus.supervisor.doofus_crash_recovery import save_checkpoint
from doofus.supervisor.doofus_cycle_checkpoint import write_checkpoint as write_cycle_ck
from doofus.supervisor.cycle_init_watchdog import rollback_init_without_progress


def write_pair(output_dir: Path, stem: str, payload: dict) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / f"{stem}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    md_lines = [f"# {stem}", "", f"**Classification:** `{payload.get('classification')}`", ""]
    for key, value in payload.items():
        if key == "classification":
            continue
        md_lines.append(f"- **{key}:** `{value}`")
    (output_dir / f"{stem}.md").write_text("\n".join(md_lines) + "\n", encoding="utf-8")


def load_baseline_checkpoint(baseline_json: str | Path | None) -> tuple[dict, dict | None, dict]:
    if baseline_json:
        raw = json.loads(Path(baseline_json).read_text(encoding="utf-8"))
    else:
        from doofus.supervisor.doofus_crash_recovery import load_checkpoint

        raw = load_checkpoint()
    baseline = extract_checkpoint(raw)
    cycle_ck = extract_cycle_checkpoint(raw) if isinstance(raw, dict) else None
    meta = {
        "input_shape": "starting_state_artifact" if cycle_ck else "raw_checkpoint",
        "validated": True,
    }
    return baseline, cycle_ck, meta


def write_containment_report(
    *,
    output_dir: Path,
    stalled_step: str,
    generation: int,
    baseline_checkpoint: dict,
    cycle_checkpoint: dict | None = None,
    backup: bool = True,
    backup_db: bool = False,
) -> dict:
    validate_checkpoint(baseline_checkpoint)
    checkpoint_backups = backup_checkpoint_files(output_dir=output_dir, label="init_timeout_containment")
    marker = STATE / "one_cycle_launch_active.marker"
    if marker.exists():
        marker.unlink()
    stop_after = stop()
    cleanup = rollback_init_without_progress(
        generation=generation,
        baseline_checkpoint=baseline_checkpoint,
        had_candidates=False,
        model_calls=0,
        stalled_step=stalled_step,
    )
    save_checkpoint(dict(baseline_checkpoint))
    if cycle_checkpoint:
        write_cycle_ck(cycle_checkpoint.get("stage", "cycle_complete"), cycle_checkpoint.get("data", {}))
    else:
        cycle_ck = cleanup.get("cycle_checkpoint_after") or {}
        write_cycle_ck(cycle_ck.get("stage", "cycle_complete"), cycle_ck.get("data", {}))
    backup_path = None
    if backup_db:
        backup_path = backup_live_db(output_dir=output_dir, label="init_timeout_containment")
    pf = inspect_live_db(target_generation=generation)
    report = {
        "classification": "DOOFUS_INIT_TIMEOUT_CONTAINMENT",
        "stalled_step": stalled_step,
        "generation": generation,
        "stop_restored": bool(stop_after.get("stop_requested")),
        "checkpoint_backups": checkpoint_backups,
        "cleanup": cleanup,
        "backup_path": str(backup_path) if backup_path else None,
        "preflight_after": pf,
    }
    write_pair(output_dir, "INIT_TIMEOUT_CONTAINMENT", report)
    return report


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Contain init timeout and restore baseline.")
    parser.add_argument(
        "--output-dir",
        default=str(WORKSPACE / "artifacts" / "doofus" / "gen1640-init-hang-repair-v1"),
    )
    parser.add_argument("--generation", type=int, default=1640)
    parser.add_argument("--stalled-step", default="inline_rescue")
    parser.add_argument("--baseline-json", default="")
    parser.add_argument("--backup-db", action="store_true")
    args = parser.parse_args()
    try:
        baseline, cycle_ck, meta = load_baseline_checkpoint(args.baseline_json or None)
    except CheckpointSchemaError as exc:
        print(json.dumps({"classification": "DOOFUS_CONTAINMENT_REFUSED", "error": str(exc)}, indent=2))
        return 1
    report = write_containment_report(
        output_dir=Path(args.output_dir),
        stalled_step=args.stalled_step,
        generation=args.generation,
        baseline_checkpoint=baseline,
        cycle_checkpoint=cycle_ck,
        backup_db=args.backup_db,
    )
    report["baseline_meta"] = meta
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
