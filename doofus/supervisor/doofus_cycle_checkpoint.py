"""Per-stage cycle checkpoints."""
from __future__ import annotations
import json
from doofus.core.doofus_paths import STATE
from doofus.core.doofus_events import utc_now

CHECKPOINT = STATE / "cycle_checkpoint.json"

def write_checkpoint(stage: str, data: dict) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    doc = {"stage": stage, "data": data, "saved_at": utc_now()}
    CHECKPOINT.write_text(json.dumps(doc, indent=2), encoding="utf-8")

def read_checkpoint() -> dict:
    if CHECKPOINT.exists():
        return json.loads(CHECKPOINT.read_text(encoding="utf-8"))
    return {"stage": "none", "data": {}}
