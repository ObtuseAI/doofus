"""Repair recipe subset of self-improvement catalog."""
from __future__ import annotations

from doofus.self_improvement.improvement_catalog import ImprovementCatalog
from doofus.self_improvement.improvement_item import ImprovementItem


def repair_recipes(catalog: ImprovementCatalog) -> list[ImprovementItem]:
    return catalog.by_type("repair_recipe")
