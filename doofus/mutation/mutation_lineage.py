"""Candidate lineage tracking."""
from __future__ import annotations

def build_lineage(candidates: list[dict]) -> dict:
    nodes = {c["candidate_id"]: {"parent": c.get("parent_id"), "generation": c.get("generation")} for c in candidates}
    return {"classification": "DOOFUS_LINEAGE_READY", "nodes": nodes, "count": len(nodes)}
