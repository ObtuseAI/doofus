"""Live DB generation preflight and guarded scrub helpers."""
from __future__ import annotations

import json
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from doofus.core import doofus_paths
from doofus.core.doofus_events import utc_now
from doofus.core.metrics_db import connect_metrics_db
from doofus.supervisor.doofus_crash_recovery import load_checkpoint
from doofus.supervisor.doofus_cycle_checkpoint import read_checkpoint


@dataclass(frozen=True)
class CheckpointState:
    checkpoint: dict
    cycle_checkpoint: dict

    @property
    def generation(self) -> int:
        return int(self.checkpoint.get("generation", -1))

    @property
    def phase(self) -> str:
        return str(self.checkpoint.get("phase") or "")

    @property
    def cycle_generation(self) -> int:
        return int(self.cycle_checkpoint.get("data", {}).get("generation", -1))

    @property
    def cycle_stage(self) -> str:
        return str(self.cycle_checkpoint.get("stage") or "")

    @property
    def ambiguous(self) -> bool:
        return (
            self.generation < 0
            or self.phase != "complete"
            or self.cycle_stage != "cycle_complete"
            or self.cycle_generation != self.generation
        )


def live_db_path() -> Path:
    return doofus_paths.METRICS_DB


def checkpoint_state() -> CheckpointState:
    return CheckpointState(
        checkpoint=load_checkpoint(),
        cycle_checkpoint=read_checkpoint(),
    )


def generation_tables(conn: sqlite3.Connection) -> list[str]:
    tables: list[str] = []
    for (table_name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
        cols = [row[1] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()]
        if "generation" in cols:
            tables.append(table_name)
    return tables


def candidate_link_tables(conn: sqlite3.Connection) -> list[str]:
    tables: list[str] = []
    for (table_name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
        cols = [row[1] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()]
        if "candidate_id" in cols and table_name != "candidates":
            tables.append(table_name)
    return tables


def _counts_for_table(
    conn: sqlite3.Connection,
    *,
    table_name: str,
    checkpoint_generation: int,
    target_generation: int,
) -> dict:
    return {
        "checkpoint_generation_count": int(
            conn.execute(
                f"SELECT COUNT(*) FROM {table_name} WHERE generation=?",
                (checkpoint_generation,),
            ).fetchone()[0]
        ),
        "target_generation_count": int(
            conn.execute(
                f"SELECT COUNT(*) FROM {table_name} WHERE generation=?",
                (target_generation,),
            ).fetchone()[0]
        ),
        "above_target_generation_count": int(
            conn.execute(
                f"SELECT COUNT(*) FROM {table_name} WHERE generation>?",
                (target_generation,),
            ).fetchone()[0]
        ),
        "max_generation": conn.execute(f"SELECT MAX(generation) FROM {table_name}").fetchone()[0],
    }


def inspect_live_db(
    *,
    checkpoint_generation: int | None = None,
    target_generation: int | None = None,
    db_path: Path | None = None,
) -> dict:
    state = checkpoint_state()
    checkpoint_generation = state.generation if checkpoint_generation is None else int(checkpoint_generation)
    target_generation = checkpoint_generation + 1 if target_generation is None else int(target_generation)
    db_path = db_path or live_db_path()

    conn = connect_metrics_db(db_path=db_path)
    try:
        tables = generation_tables(conn)
        table_counts = {
            table_name: _counts_for_table(
                conn,
                table_name=table_name,
                checkpoint_generation=checkpoint_generation,
                target_generation=target_generation,
            )
            for table_name in tables
        }
    finally:
        conn.close()

    target_generation_total = sum(item["target_generation_count"] for item in table_counts.values())
    above_target_generation_total = sum(item["above_target_generation_count"] for item in table_counts.values())
    max_generation = max(
        (int(item["max_generation"]) for item in table_counts.values() if item["max_generation"] is not None),
        default=-1,
    )

    mismatch = {
        "checkpoint_vs_cycle": state.generation != state.cycle_generation,
        "checkpoint_vs_db_max": max_generation > checkpoint_generation,
        "cycle_vs_db_max": max_generation > state.cycle_generation,
    }
    blockers: list[str] = []
    warnings: list[str] = []
    if state.ambiguous:
        blockers.append("checkpoint_state_ambiguous")
    if target_generation_total > 0:
        blockers.append("target_generation_already_present")
    if above_target_generation_total > 0:
        blockers.append("rows_present_above_target_generation")
    if mismatch["checkpoint_vs_cycle"]:
        blockers.append("checkpoint_cycle_generation_mismatch")
    if mismatch["checkpoint_vs_db_max"]:
        warnings.append("db_max_generation_above_checkpoint")

    return {
        "classification": "DOOFUS_LIVE_DB_PREFLIGHT",
        "checked_at": utc_now(),
        "db_path": str(db_path),
        "checkpoint": state.checkpoint,
        "cycle_checkpoint": state.cycle_checkpoint,
        "checkpoint_generation": checkpoint_generation,
        "target_generation": target_generation,
        "generation_tables": tables,
        "table_counts": table_counts,
        "target_generation_total": target_generation_total,
        "above_target_generation_total": above_target_generation_total,
        "db_max_generation": max_generation,
        "checkpoint_state_ambiguous": state.ambiguous,
        "mismatch": mismatch,
        "blockers": blockers,
        "warnings": warnings,
        "contamination_detected": bool(
            target_generation_total > 0
            or above_target_generation_total > 0
            or mismatch["checkpoint_vs_cycle"]
            or mismatch["checkpoint_vs_db_max"]
        ),
    }


def backup_live_db(*, output_dir: Path, label: str, db_path: Path | None = None) -> Path:
    db_path = db_path or live_db_path()
    output_dir.mkdir(parents=True, exist_ok=True)
    backup_path = output_dir / f"{db_path.stem}_{label}_{utc_now().replace(':', '').replace('-', '')}.sqlite"
    shutil.copy2(db_path, backup_path)
    return backup_path


def _write_markdown_report(path: Path, report: dict) -> None:
    summary = report.get("after") or report.get("before") or report
    lines = [
        f"# {report['classification']}",
        "",
        f"- checked_at: `{report['checked_at']}`",
        f"- db_path: `{report.get('db_path') or summary.get('db_path')}`",
        f"- checkpoint_generation: `{summary.get('checkpoint_generation')}`",
        f"- target_generation: `{summary.get('target_generation')}`",
        f"- db_max_generation: `{summary.get('db_max_generation')}`",
        f"- contamination_detected: `{summary.get('contamination_detected')}`",
        "",
        "## Blockers",
    ]
    blockers = summary.get("blockers") or report.get("blockers") or []
    if blockers:
        for blocker in blockers:
            lines.append(f"- {blocker}")
    else:
        lines.append("- none")
    lines.extend(["", "## Warnings"])
    warnings = summary.get("warnings") or report.get("warnings") or []
    if warnings:
        for warning in warnings:
            lines.append(f"- {warning}")
    else:
        lines.append("- none")
    lines.extend(["", "## Table Counts"])
    for table_name in sorted(summary.get("table_counts", {})):
        item = summary["table_counts"][table_name]
        lines.append(
            f"- `{table_name}` checkpoint={item['checkpoint_generation_count']} "
            f"target={item['target_generation_count']} above_target={item['above_target_generation_count']} "
            f"max_generation={item['max_generation']}"
        )
    if report.get("deletions"):
        lines.extend(["", "## Deletions"])
        for table_name in sorted(report["deletions"]):
            lines.append(f"- `{table_name}` deleted_rows={report['deletions'][table_name]}")
    if report.get("backup_path"):
        lines.extend(["", "## Backup"])
        lines.append(f"- `{report['backup_path']}`")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_report(*, report: dict, output_dir: Path, stem: str) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{stem}.json"
    md_path = output_dir / f"{stem}.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    _write_markdown_report(md_path, report)
    return json_path, md_path


def scrub_live_db(
    *,
    mode: str,
    confirm: bool,
    output_dir: Path,
    checkpoint_generation: int | None = None,
    target_generation: int | None = None,
    db_path: Path | None = None,
) -> dict:
    if mode not in {"scrub_target_generation", "scrub_above_checkpoint"}:
        raise ValueError(f"unsupported scrub mode: {mode}")
    if not confirm:
        return {
            "classification": "DOOFUS_LIVE_DB_PREFLIGHT_REFUSED",
            "checked_at": utc_now(),
            "mode": mode,
            "reason": "confirm_required",
        }

    before = inspect_live_db(
        checkpoint_generation=checkpoint_generation,
        target_generation=target_generation,
        db_path=db_path,
    )
    if before["checkpoint_state_ambiguous"]:
        return {
            "classification": "DOOFUS_LIVE_DB_PREFLIGHT_REFUSED",
            "checked_at": utc_now(),
            "mode": mode,
            "reason": "checkpoint_state_ambiguous",
            "before": before,
        }

    checkpoint_generation = before["checkpoint_generation"]
    target_generation = before["target_generation"]
    db_path = Path(before["db_path"])
    backup_path = backup_live_db(output_dir=output_dir, label=mode, db_path=db_path)

    conn = connect_metrics_db(db_path=db_path, timeout=30.0)
    deletions: dict[str, int | None] = {}
    try:
        tables = generation_tables(conn)
        linked_tables = candidate_link_tables(conn)
        if mode == "scrub_target_generation":
            where = "generation=?"
            params = (target_generation,)
        else:
            where = "generation>?"
            params = (checkpoint_generation,)

        candidate_ids = [
            row[0]
            for row in conn.execute(f"SELECT candidate_id FROM candidates WHERE {where}", params).fetchall()
        ]

        conn.execute("BEGIN IMMEDIATE")
        for table_name in tables:
            deletions[table_name] = conn.execute(
                f"DELETE FROM {table_name} WHERE {where}",
                params,
            ).rowcount
        for table_name in linked_tables:
            if not candidate_ids:
                deletions.setdefault(table_name, 0)
                continue
            placeholders = ",".join("?" for _ in candidate_ids)
            deletions[table_name] = conn.execute(
                f"DELETE FROM {table_name} WHERE candidate_id IN ({placeholders})",
                tuple(candidate_ids),
            ).rowcount
        conn.commit()
    finally:
        conn.close()

    after = inspect_live_db(
        checkpoint_generation=checkpoint_generation,
        target_generation=target_generation,
        db_path=db_path,
    )
    return {
        "classification": "DOOFUS_LIVE_DB_PREFLIGHT_SCRUBBED",
        "checked_at": utc_now(),
        "mode": mode,
        "db_path": str(db_path),
        "backup_path": str(backup_path),
        "before": before,
        "after": after,
        "deletions": deletions,
    }
