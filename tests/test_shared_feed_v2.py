"""Tests for Feed V2 indexes and Blunder consumer package."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

WORKSPACE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE))

from scripts.doofus_shared_feed_v2 import (
    build_v2_indexes,
    emit_blunder_consumer_package,
    score_item,
    validate_lean_feed,
    verify_feed_v2,
    FEED_V2_SIZE_CAP,
)
from scripts.doofus_shared_improvement_feed import build_feed_items, feed_schema, publish_feed, build_blunder_bundle, mine_discoveries


@pytest.fixture
def temp_feed(tmp_path: Path) -> Path:
    dest = tmp_path / "feed"
    items = build_feed_items()[:42]
    schema = feed_schema()
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "FEED_SCHEMA.json").write_text(json.dumps(schema), encoding="utf-8")
    publish_feed(
        staging_root=staging,
        dest_root=dest,
        items=items,
        schema=schema,
        mined=mine_discoveries(),
        blunder_bundle=build_blunder_bundle(items),
    )
    return dest


def test_deterministic_scoring():
    item = build_feed_items()[0]
    a = score_item(item)
    b = score_item(item)
    assert a == b
    assert a["recommended_import_priority"] in {
        "P0_IMPORT_NOW", "P1_IMPORT_NEXT", "P2_USE_AS_REFERENCE", "P3_REVIEW_LATER", "DO_NOT_IMPORT_DIRECTLY"
    }


def test_v2_indexes_generated(temp_feed: Path):
    items = [json.loads(p.read_text()) for p in (temp_feed / "latest").glob("*.json")]
    result = build_v2_indexes(temp_feed, items)
    assert result["classification"] == "DOOFUS_FEED_V2_INDEX_BUILD_COMPLETE"
    assert (temp_feed / "indexes" / "BLUNDER_PRIORITY_INDEX.json").exists()
    assert (temp_feed / "indexes" / "DEDUPE_INDEX.json").exists()


def test_blunder_consumer_package(temp_feed: Path):
    items = [json.loads(p.read_text()) for p in (temp_feed / "latest").glob("*.json")]
    build_v2_indexes(temp_feed, items)
    r = emit_blunder_consumer_package(temp_feed, items)
    pkg = temp_feed / "by_project" / "blunder" / "consumer_package"
    assert r["classification"] == "DOOFUS_BLUNDER_CONSUMER_PACKAGE_COMPLETE"
    assert (pkg / "BLUNDER_CONSUMER_SPEC.json").exists()
    assert (pkg / "BLUNDER_FEED_CONSUMER_BUILD_PROMPT.md").exists()


def test_no_db_in_feed(temp_feed: Path):
    db = list(temp_feed.rglob("*.sqlite"))
    assert db == []


def test_dedupe_index_unique(temp_feed: Path):
    items = [json.loads(p.read_text()) for p in (temp_feed / "latest").glob("*.json")]
    build_v2_indexes(temp_feed, items)
    dedupe = json.loads((temp_feed / "indexes" / "DEDUPE_INDEX.json").read_text())
    keys = list(dedupe["dedupe_keys"].keys())
    assert len(keys) == len(set(keys))


def test_feed_v2_verification(temp_feed: Path):
    items = [json.loads(p.read_text()) for p in (temp_feed / "latest").glob("*.json")]
    build_v2_indexes(temp_feed, items)
    emit_blunder_consumer_package(temp_feed, items)
    v = verify_feed_v2(temp_feed)
    assert v["checks"]["indexes_exist"] is True
    assert v["checks"]["no_db_files"] is True
