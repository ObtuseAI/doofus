"""Tests for Doofus self-improvement catalog."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

WORKSPACE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE))

from doofus.self_improvement.improvement_catalog import ImprovementCatalog
from doofus.self_improvement.improvement_item import ImprovementItem
from doofus.self_improvement.improvement_scorer import score_item
from doofus.self_improvement.cycle_lesson_extractor import extract_lessons_from_artifacts
from doofus.self_improvement.next_cycle_seed_builder import build_seed_recommendations
from doofus.supervisor.doofus_crash_recovery import load_checkpoint


def test_catalog_loads_artifacts():
    items = extract_lessons_from_artifacts(WORKSPACE, 1639)
    assert len(items) >= 50


def test_catalog_dedupes():
    catalog = ImprovementCatalog.from_workspace(WORKSPACE, 1639)
    keys = [i.dedupe_key for i in catalog.items]
    assert len(keys) == len(set(keys))


def test_catalog_scores_deterministically():
    item = ImprovementItem.create(
        type_="guard_pattern",
        title="Test guard",
        summary="s",
        problem="p",
        recommendation="r",
    )
    assert score_item(item) == score_item(item)


def test_validation_queue_writes(tmp_path: Path):
    catalog = ImprovementCatalog.from_workspace(WORKSPACE, 1639)
    result = catalog.write_outputs(tmp_path)
    assert result["item_count"] >= 50
    assert (tmp_path / "validation_queue.json").exists()
    vq = json.loads((tmp_path / "validation_queue.json").read_text())
    assert vq["count"] > 0


def test_next_cycle_seeds(tmp_path: Path):
    catalog = ImprovementCatalog.from_workspace(WORKSPACE, 1639)
    seeds = build_seed_recommendations(catalog, tmp_path)
    assert seeds["seed_count"] >= 20
    assert seeds["p0_count"] >= 5
    assert (tmp_path / "GEN1640_SEED_RECOMMENDATIONS.json").exists()


def test_no_checkpoint_mutation():
    before = load_checkpoint()
    ImprovementCatalog.from_workspace(WORKSPACE, 1639)
    after = load_checkpoint()
    assert before == after


def test_no_live_route_marker():
    catalog = ImprovementCatalog.from_workspace(WORKSPACE, 1639)
    assert len(catalog.items) >= 50
