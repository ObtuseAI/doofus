"""Apply mutations to candidates."""
from __future__ import annotations
import random
from doofus.mutation.trait_library import TRAITS
from doofus.meta.gep.gene_library import genes_to_traits, trait_to_gene
from doofus.meta.gep.gep_schema import Gene

def mutate_candidate(candidate: dict, rng: random.Random | None = None) -> dict:
    rng = rng or random.Random()
    traits = list(candidate.get("traits", []))
    if traits and rng.random() < 0.5:
        traits[rng.randrange(len(traits))] = rng.choice(TRAITS)
    else:
        traits.append(rng.choice(TRAITS))
    child = dict(candidate)
    child["traits"] = sorted(set(traits))
    child["mutation_type"] = "trait_mutation"
    child["parent_id"] = candidate.get("candidate_id")
    return child


def gene_crossover(parent_a: dict, parent_b: dict, rng: random.Random | None = None) -> dict:
    """GEP gene crossover between two parents."""
    rng = rng or random.Random()
    genes_a = [trait_to_gene(t) for t in (parent_a.get("traits") or [])[:4]]
    genes_b = [trait_to_gene(t) for t in (parent_b.get("traits") or [])[:4]]
    merged: list[Gene] = []
    for i in range(max(len(genes_a), len(genes_b))):
        if i < len(genes_a) and (i >= len(genes_b) or rng.random() < 0.5):
            merged.append(genes_a[i])
        elif i < len(genes_b):
            merged.append(genes_b[i])
    traits = genes_to_traits(merged)
    if len(traits) < 2:
        traits = sorted(set((parent_a.get("traits") or [])[:2] + (parent_b.get("traits") or [])[:2]))
    child = dict(parent_a)
    child["traits"] = sorted(set(traits))[:6]
    child["mutation_type"] = "gene_crossover"
    child["parent_id"] = parent_a.get("candidate_id")
    child["parent_b_id"] = parent_b.get("candidate_id")
    return child
