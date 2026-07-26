"""Conversion verdict dashboard panel."""
from __future__ import annotations

import json
from pathlib import Path

from doofus.core.doofus_paths import PROOF_BUILDER_TUNING_DIR


def get_conversion_panel() -> dict:
    p = PROOF_BUILDER_TUNING_DIR / "b1106_conversion_analysis.json"
    if not p.exists():
        return {"verdict": "pending", "status": "pending"}
    d = json.loads(p.read_text(encoding="utf-8"))
    return {"verdict": d.get("verdict"), "classification": d.get("classification"), "proof_builder": d.get("proof_builder", {})}
