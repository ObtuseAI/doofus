"""Typed gene library mapping loci to traits."""
from __future__ import annotations

from doofus.meta.gep.gep_schema import Gene
from doofus.mutation.trait_library import TRAITS

LOCUS_TRAIT_MAP = {
    "replay_locus": "replay_stability",
    "proof_locus": "proof_density",
    "arena_locus": "arena_agent_arcade",
    "generalization_locus": "generalization_pressure",
    "compounding_locus": "compounding_focus",
}

TRAIT_LOCUS_MAP = {v: k for k, v in LOCUS_TRAIT_MAP.items()}


def trait_to_gene(trait: str, weight: float = 1.0) -> Gene:
    locus = TRAIT_LOCUS_MAP.get(trait, f"custom_{trait}")
    return Gene(locus=locus, allele=trait, expression_weight=weight)


def genes_to_traits(genes: list[Gene]) -> list[str]:
    out: list[str] = []
    for g in genes:
        if g.allele in TRAITS and g.allele not in out:
            out.append(g.allele)
    return out


def default_gene_pool() -> list[Gene]:
    return [trait_to_gene(t, 0.5) for t in TRAITS[:6]]
