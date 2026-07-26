"""Safety gate for candidates."""
from __future__ import annotations

FORBIDDEN_TRAITS = frozenset({
    "wanefall_mutation", "veloren_source_mutation", "chris_mutation", "frankenstein_mutation",
    "public_deploy", "rom_download", "forced_promotion", "agi_claim", "foundry_proven_claim",
})

def check_candidate_safety(candidate: dict) -> dict:
    traits = set(candidate.get("traits", []))
    bad = traits & FORBIDDEN_TRAITS
    score = 1.0 if not bad else 0.0
    return {"passes": not bad, "score_safety": score, "violations": sorted(bad)}
