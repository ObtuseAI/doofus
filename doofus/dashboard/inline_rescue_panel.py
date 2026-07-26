"""Inline rescue dashboard panel."""
from __future__ import annotations

from doofus.proof.proof_builder_queue import queue_summary


def get_inline_rescue_panel() -> dict:
    q = queue_summary()
    return {"active": q.get("enabled"), **q}
