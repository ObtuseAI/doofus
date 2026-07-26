"""Mutation method subset of self-improvement catalog."""
from __future__ import annotations

from doofus.self_improvement.improvement_catalog import ImprovementCatalog
from doofus.self_improvement.improvement_item import ImprovementItem


def mutation_methods(catalog: ImprovementCatalog) -> list[ImprovementItem]:
    return catalog.by_type("mutation_method")
