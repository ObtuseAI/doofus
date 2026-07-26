"""Apply validated model mutation proposals to candidates."""
from __future__ import annotations

import random

from doofus.mutation.trait_library import TRAITS
from doofus.safety.doofus_safety_gate import FORBIDDEN_TRAITS

_ALLOWED = frozenset(TRAITS)


def _extract_traits(proposal: dict) -> list[str]:
    if not isinstance(proposal, dict):
        return []
    entries = proposal.get("proposals")
    if isinstance(entries, list) and entries:
        first = entries[0]
        if isinstance(first, dict):
            raw = first.get("traits") or first.get("mutation_traits") or []
            return [str(t) for t in raw if isinstance(t, str)]
    raw = proposal.get("traits") or proposal.get("mutation_traits") or []
    return [str(t) for t in raw if isinstance(t, str)]


def apply_proposal_to_candidate(candidate: dict, proposal: dict, *, rng: random.Random | None = None) -> dict:
    """Merge model-proposed traits into one candidate (safety-filtered)."""
    rng = rng or random.Random()
    traits = [t for t in _extract_traits(proposal) if t in _ALLOWED and t not in FORBIDDEN_TRAITS]
    if not traits:
        return candidate
    merged = sorted(set(list(candidate.get("traits") or []) + traits))
    if len(merged) > 6:
        merged = rng.sample(merged, k=6)
    child = dict(candidate)
    child["traits"] = sorted(set(merged))
    child["mutation_type"] = "model_guided_mutation"
    return child
