"""Git-style snapshots for codeevolve rollback."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from doofus.core.doofus_events import utc_now
from doofus.core.doofus_paths import STATE

SNAPSHOT_DIR = STATE / "codeevolve" / "snapshots"
PENDING_DIFF = STATE / "codeevolve" / "pending_diff.json"
META_FILE = STATE / "codeevolve" / "rollback_meta.json"


def snapshot_module(module_path: Path, label: str) -> Path:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    dest = SNAPSHOT_DIR / f"{label}_{module_path.name}"
    shutil.copy2(module_path, dest)
    return dest


def save_pending_diff(target_id: str, summary: str, fitness: float) -> None:
    PENDING_DIFF.parent.mkdir(parents=True, exist_ok=True)
    PENDING_DIFF.write_text(json.dumps({
        "target_id": target_id,
        "summary": summary,
        "fitness": fitness,
        "created_at": utc_now(),
    }, indent=2), encoding="utf-8")


def record_baseline_promotion_rate(rate: float) -> None:
    meta = _load_meta()
    meta.setdefault("promotion_rates", []).append({"rate": rate, "at": utc_now()})
    meta["promotion_rates"] = meta["promotion_rates"][-20:]
    _save_meta(meta)


def should_rollback(current_rate: float, baseline_rate: float) -> bool:
    if baseline_rate <= 0:
        return False
    drop = (baseline_rate - current_rate) / baseline_rate
    return drop > 0.15


def rollback_to_snapshot(module_path: Path, label: str) -> bool:
    snap = SNAPSHOT_DIR / f"{label}_{module_path.name}"
    if not snap.exists():
        return False
    shutil.copy2(snap, module_path)
    return True


def _load_meta() -> dict:
    if not META_FILE.exists():
        return {}
    return json.loads(META_FILE.read_text(encoding="utf-8"))


def _save_meta(meta: dict) -> None:
    META_FILE.parent.mkdir(parents=True, exist_ok=True)
    META_FILE.write_text(json.dumps(meta, indent=2), encoding="utf-8")


def get_snapshot() -> dict:
    meta = _load_meta()
    pending = None
    if PENDING_DIFF.exists():
        pending = json.loads(PENDING_DIFF.read_text(encoding="utf-8"))
    return {"meta": meta, "pending_diff": pending, "snapshots": len(list(SNAPSHOT_DIR.glob("*"))) if SNAPSHOT_DIR.exists() else 0}
