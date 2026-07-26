"""Backup-first scrub of orphan map_elites_cells gen1638 rows."""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from doofus.core import doofus_paths
from doofus.core.doofus_events import utc_now
from doofus.runtime.live_db_preflight import inspect_live_db, write_report


def _export_orphan_rows(output_dir: Path) -> tuple[Path, list[dict]]:
    conn = sqlite3.connect(doofus_paths.METRICS_DB, timeout=30)
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(map_elites_cells)").fetchall()]
        rows = [
            dict(zip(cols, row))
            for row in conn.execute("SELECT * FROM map_elites_cells WHERE generation=1638").fetchall()
        ]
    finally:
        conn.close()
    path = output_dir / f"map_elites_gen1638_orphan_rows_backup_{utc_now().replace(':', '').replace('-', '')}.json"
    path.write_text(json.dumps({"exported_at": utc_now(), "rows": rows}, indent=2), encoding="utf-8")
    return path, rows


def _sqlite_backup(source: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True, timeout=60)
    dst = sqlite3.connect(dest, timeout=60)
    try:
        started = time.perf_counter()
        src.backup(dst)
        elapsed = time.perf_counter() - started
        print(f"sqlite backup completed in {elapsed:.1f}s -> {dest}", flush=True)
    finally:
        dst.close()
        src.close()


def main() -> int:
    output_dir = WORKSPACE / "artifacts" / "doofus" / "gen1638-db-scrub-readiness-v1"
    output_dir.mkdir(parents=True, exist_ok=True)
    db = doofus_paths.METRICS_DB

    print("preflight before scrub", flush=True)
    before = inspect_live_db(target_generation=1638)
    if int(before.get("target_generation_total") or 0) != 2:
        print(json.dumps({"error": "unexpected contamination scope", "before": before}, indent=2))
        return 1

    row_backup_path, orphan_rows = _export_orphan_rows(output_dir)
    print(f"row backup: {row_backup_path} ({len(orphan_rows)} rows)", flush=True)

    label = "scrub_target_generation"
    backup = output_dir / f"doofus_metrics_{label}_{utc_now().replace(':', '').replace('-', '')}.sqlite"
    print(f"starting sqlite online backup -> {backup}", flush=True)
    _sqlite_backup(db, backup)

    conn = sqlite3.connect(db, timeout=60)
    try:
        conn.execute("PRAGMA busy_timeout=60000")
        conn.execute("BEGIN IMMEDIATE")
        deleted = conn.execute("DELETE FROM map_elites_cells WHERE generation=1638").rowcount
        conn.commit()
    finally:
        conn.close()
    print(f"deleted {deleted} map_elites_cells rows at generation 1638", flush=True)

    after = inspect_live_db(target_generation=1638)
    result = {
        "classification": "DOOFUS_LIVE_DB_PREFLIGHT_SCRUBBED",
        "checked_at": utc_now(),
        "mode": "scrub_target_generation",
        "db_path": str(db),
        "backup_path": str(backup),
        "row_backup_path": str(row_backup_path),
        "orphan_rows_exported": orphan_rows,
        "before": before,
        "after": after,
        "deletions": {"map_elites_cells": deleted},
    }
    write_report(report=result, output_dir=output_dir, stem="live_db_scrub_result")
    (output_dir / "live_db_scrub_result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    ok = (
        deleted == 2
        and int(after.get("target_generation_total") or 0) == 0
        and int(after.get("db_max_generation") or -1) == 1637
    )
    print(json.dumps({"ok": ok, "deleted": deleted, "db_max_generation": after.get("db_max_generation")}, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
