"""Proof-builder dashboard panel."""
from __future__ import annotations

from doofus.proof.proof_builder_queue import queue_summary


def get_proof_builder_panel() -> dict:
    q = queue_summary()
    return {"enabled": q.get("enabled"), **q}
