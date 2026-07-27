"""Extract and validate checkpoint objects from containment baseline inputs."""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from doofus.core.doofus_events import utc_now
from doofus.supervisor.doofus_crash_recovery import CHECKPOINT
from doofus.supervisor.doofus_cycle_checkpoint import CHECKPOINT as CYCLE_CHECKPOINT

CHECKPOINT_REQUIRED = frozenset({"generation", "phase", "baseline_score", "run_id"})
CYCLE_CHECKPOINT_REQUIRED = frozenset({"stage", "data"})


class CheckpointSchemaError(ValueError):
    pass


def is_raw_checkpoint(obj: dict[str, Any]) -> bool:
    return CHECKPOINT_REQUIRED.issubset(obj.keys()) and "classification" not in obj


def is_starting_state_artifact(obj: dict[str, Any]) -> bool:
    if not isinstance(obj.get("checkpoint"), dict):
        return False
    nested = obj["checkpoint"]
    return is_raw_checkpoint(nested) and (
        "STARTING_STATE" in str(obj.get("classification", ""))
        or "branch" in obj
        or "commit" in obj
        or "retry_packet_hash" in obj
    )


def extract_checkpoint(obj: dict[str, Any]) -> dict[str, Any]:
    if is_raw_checkpoint(obj):
        candidate = dict(obj)
    elif is_starting_state_artifact(obj):
        candidate = dict(obj["checkpoint"])
    elif isinstance(obj.get("checkpoint"), dict) and is_raw_checkpoint(obj["checkpoint"]):
        candidate = dict(obj["checkpoint"])
    else:
        raise CheckpointSchemaError(
            "baseline JSON must be a raw checkpoint object or a starting-state artifact with nested checkpoint"
        )
    validate_checkpoint(candidate)
    return candidate


def extract_cycle_checkpoint(obj: dict[str, Any]) -> dict[str, Any] | None:
    if is_starting_state_artifact(obj) and isinstance(obj.get("cycle_checkpoint"), dict):
        cc = obj["cycle_checkpoint"]
        if CYCLE_CHECKPOINT_REQUIRED.issubset(cc.keys()):
            return dict(cc)
    return None


def validate_checkpoint(checkpoint: dict[str, Any]) -> None:
    missing = CHECKPOINT_REQUIRED - set(checkpoint.keys())
    if missing:
        raise CheckpointSchemaError(f"checkpoint missing required keys: {sorted(missing)}")
    if not isinstance(checkpoint.get("generation"), int):
        raise CheckpointSchemaError("checkpoint.generation must be int")
    if not isinstance(checkpoint.get("phase"), str):
        raise CheckpointSchemaError("checkpoint.phase must be str")


def validate_cycle_checkpoint(cycle_checkpoint: dict[str, Any]) -> None:
    missing = CYCLE_CHECKPOINT_REQUIRED - set(cycle_checkpoint.keys())
    if missing:
        raise CheckpointSchemaError(f"cycle_checkpoint missing required keys: {sorted(missing)}")
    data = cycle_checkpoint.get("data")
    if not isinstance(data, dict):
        raise CheckpointSchemaError("cycle_checkpoint.data must be object")


def backup_checkpoint_files(*, output_dir: Path | None = None, label: str = "containment") -> dict[str, str]:
    output_dir = output_dir or CHECKPOINT.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = utc_now().replace(":", "").replace("+", "p")
    backups: dict[str, str] = {}
    for src in (CHECKPOINT, CYCLE_CHECKPOINT):
        if src.exists():
            dest = output_dir / f"{src.stem}_{label}_{stamp}{src.suffix}"
            shutil.copy2(src, dest)
            backups[src.name] = str(dest)
    return backups
