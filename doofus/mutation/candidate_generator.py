"""Generate mutation candidates with elite-weighted parent selection."""
from __future__ import annotations

import hashlib
import os
import random

from doofus.config.meta_evolution_config import map_elites_enabled
from doofus.core.doofus_events import utc_now
from doofus.evolution.adaptive_mutation_pressure import candidate_count_for_cycle
from doofus.evolution.branch_retirement import is_branch_retired
from doofus.evolution.elite_parent_selector import select_parents
from doofus.evolution.evolution_policy import evolution_pressure_enabled
from doofus.evolution.map_elites_selector import select_map_elites_parents
from doofus.meta.aevolve.algorithm_selector import select_algorithms_for_cycle, record_outcome
from doofus.meta.gep.capsule_store import inject_capsule_traits, record_reuse, sample_capsule
from doofus.meta.gepa.prompt_store import get_active
from doofus.mutation.lineage_store import load_promoted_parents, load_top_scoring_parents
from doofus.mutation.mutation_engine import gene_crossover, mutate_candidate
from doofus.mutation.trait_library import TRAITS

GEPA_TRAITS = ("arena_agent_arcade", "proof_density", "replay_stability", "generalization_pressure")


def _new_id(generation: int, salt: str) -> str:
    return f"DOOFUS_{generation}_{hashlib.sha256(salt.encode()).hexdigest()[:10]}"


def _fresh_candidate(generation: int, i: int, rng: random.Random, parent_id: str | None = None) -> dict:
    tmin = int(os.environ.get("DOOFUS_TRAITS_MIN_PER_CANDIDATE", "2"))
    tmax = int(os.environ.get("DOOFUS_TRAITS_MAX_PER_CANDIDATE", "4"))
    tmax = max(tmin, tmax)
    return {
        "candidate_id": _new_id(generation, f"fresh:{i}:{rng.random()}"),
        "parent_id": parent_id,
        "generation": generation,
        "traits": rng.sample(TRAITS, k=rng.randint(tmin, min(tmax, len(TRAITS)))),
        "mutation_type": "local_trait_shuffle",
        "arena_targets": ["agent_arcade", "dry_replay"],
        "status": "generated",
        "created_at": utc_now(),
    }


def _capsule_rate() -> float:
    return float(os.environ.get("DOOFUS_CAPSULE_INJECTION_RATE", "0.15"))


def _gepa_trait_bias(child: dict, rng: random.Random) -> dict:
    """Bias traits toward GEPA-evolved prompt keywords."""
    prompt = get_active("mutation").lower()
    traits = list(child.get("traits") or [])
    for t in GEPA_TRAITS:
        if t in prompt and t not in traits and t in TRAITS:
            traits.append(t)
    if len(traits) < 3:
        for t in GEPA_TRAITS:
            if t not in traits and t in TRAITS and rng.random() < 0.4:
                traits.append(t)
    child = dict(child)
    child["traits"] = sorted(set(traits))[:6]
    child["mutation_type"] = "gepa_reflective"
    return child


def _apply_algorithm(parent: dict, parent_b: dict | None, algo: str, rng: random.Random) -> dict:
    if not parent.get("candidate_id"):
        return _fresh_candidate(parent.get("generation") or 0, 0, rng)
    if algo == "gene_crossover" and parent_b and parent_b.get("candidate_id"):
        return gene_crossover(parent, parent_b, rng)
    if algo == "gepa_reflective":
        return _gepa_trait_bias(mutate_candidate(parent, rng), rng)
    if algo == "map_elites_niche":
        child = mutate_candidate(parent, rng)
        child["mutation_type"] = "map_elites_niche"
        if parent.get("cell_key"):
            child["parent_cell_key"] = parent["cell_key"]
        return child
    if algo == "model_guided":
        child = mutate_candidate(parent, rng)
        child["mutation_type"] = "model_guided_pending"
        child["algorithm_id"] = "model_guided"
        return child
    return mutate_candidate(parent, rng)


def generate_candidates(generation: int, count: int = 3, seed: int | None = None) -> list[dict]:
    rng = random.Random(seed if seed is not None else generation)
    return [_fresh_candidate(generation, i, rng) for i in range(count)]


def generate_cycle_candidates(generation: int, count: int | None = None, seed: int | None = None) -> list[dict]:
    if count is None:
        count = candidate_count_for_cycle() if evolution_pressure_enabled() else 3
    rng = random.Random(seed if seed is not None else generation)
    if map_elites_enabled():
        parents = select_map_elites_parents(limit=count * 2, seed=generation)
    else:
        parents = select_parents(limit=count * 2)
    if not parents:
        parents = [
            p for p in (load_promoted_parents(limit=count * 2) or load_top_scoring_parents(limit=count * 2))
            if not is_branch_retired(p.get("candidate_id"))
        ]
    if not parents:
        return generate_candidates(generation, count, seed)

    algos = select_algorithms_for_cycle(count, seed=generation)
    out: list[dict] = []
    for i in range(count):
        parent = parents[i % len(parents)]
        parent_b = parents[(i + 1) % len(parents)] if len(parents) > 1 else None
        algo = algos[i] if i < len(algos) else "trait_shuffle"
        child = _apply_algorithm(parent, parent_b, algo, rng)
        child["candidate_id"] = _new_id(generation, f"child:{parent.get('candidate_id', 'x')}:{i}:{algo}")
        child["generation"] = generation
        child["algorithm_id"] = algo
        child["arena_targets"] = list(parent.get("arena_targets") or ["agent_arcade", "dry_replay"])
        child["status"] = "generated"
        child["created_at"] = utc_now()
        if rng.random() < _capsule_rate():
            cap = sample_capsule()
            if cap:
                child = inject_capsule_traits(child, cap)
                child["capsule_injected"] = True
                record_reuse(cap.capsule_id)
        double_rate = float(os.environ.get("DOOFUS_CAPSULE_DOUBLE_INJECTION_RATE", "0"))
        if double_rate > 0 and rng.random() < double_rate:
            cap2 = sample_capsule()
            if cap2:
                child = inject_capsule_traits(child, cap2)
                child["capsule_double_injected"] = True
                record_reuse(cap2.capsule_id)
        out.append(child)
    return out


def record_candidate_outcome(candidate: dict, *, promoted: bool, shadow: bool = False) -> None:
    algo = candidate.get("algorithm_id") or candidate.get("mutation_type") or "trait_shuffle"
    record_outcome(algo, promoted=promoted or shadow)
