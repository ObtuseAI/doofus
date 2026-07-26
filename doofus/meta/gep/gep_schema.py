"""GEP schema — Genes, Capsules, EvolutionEvents (EvoMap-inspired)."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Gene(BaseModel):
    locus: str
    allele: str
    expression_weight: float = Field(default=1.0, ge=0.0, le=1.0)


class Capsule(BaseModel):
    capsule_id: str
    genes: list[Gene] = Field(default_factory=list)
    fitness: float = 0.0
    reuse_count: int = 0
    strategy_name: str = ""
    created_at: str = ""


class EvolutionEvent(BaseModel):
    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str = ""


class Strategy(BaseModel):
    strategy_id: str
    algorithm_id: str
    capsule_refs: list[str] = Field(default_factory=list)
    fitness: float = 0.0
