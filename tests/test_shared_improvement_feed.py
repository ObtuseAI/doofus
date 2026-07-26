"""Tests for shared improvement feed writer."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

WORKSPACE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE))

from scripts.doofus_shared_improvement_feed import (
    build_feed_items,
    feed_schema,
    is_excluded_path,
    resolve_feed_destination,
    validate_feed_item,
    verify_feed,
    publish_feed,
    FEED_SIZE_CAP_BYTES,
    SECRET_NAMES,
    DB_SUFFIXES,
)


def test_feed_schema_has_required_fields():
    schema = feed_schema()
    assert "id" in schema["required_fields"]
    assert "guard_pattern" in schema["allowed_types"]
    assert "validated" in schema["allowed_statuses"]


def test_build_feed_items_meets_minimum_count():
    items = build_feed_items()
    assert len(items) >= 40
    blunder = [i for i in items if i["primary_target"] == "blunder" or "blunder" in i["target_projects"]]
    assert len(blunder) >= 10


def test_validate_feed_item_passes_for_built_items():
    schema = feed_schema()
    for item in build_feed_items()[:5]:
        assert validate_feed_item(item, schema) == []


def test_dedupe_keys_unique_in_catalog():
    keys = [i["dedupe_key"] for i in build_feed_items()]
    assert len(keys) == len(set(keys))


def test_db_paths_excluded(tmp_path: Path):
    db = tmp_path / "metrics.sqlite"
    db.write_bytes(b"x" * 100)
    assert is_excluded_path(db) is True


def test_secret_names_excluded(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text("SECRET=1", encoding="utf-8")
    assert is_excluded_path(env) is True


def test_resolve_destination_not_inside_repo():
    dest, method, _ = resolve_feed_destination()
    assert dest is not None
    root = WORKSPACE.resolve()
    dest_resolved = dest.resolve()
    assert root not in dest_resolved.parents or method == "local_staging_fallback"


def test_publish_to_staging_no_db_no_secrets(tmp_path: Path):
    schema = feed_schema()
    items = build_feed_items()[:42]
    from scripts.doofus_shared_improvement_feed import build_blunder_bundle, mine_discoveries

    staging = tmp_path / "artifact_out"
    staging.mkdir()
    (staging / "FEED_SCHEMA.json").write_text(json.dumps(schema), encoding="utf-8")
    (staging / "MINED_DISCOVERIES_RAW.json").write_text("{}", encoding="utf-8")
    dest = tmp_path / "feed"
    result = publish_feed(
        staging_root=staging,
        dest_root=dest,
        items=items,
        schema=schema,
        mined=mine_discoveries(),
        blunder_bundle=build_blunder_bundle(items),
        dry_run=False,
    )
    assert result["classification"] == "DOOFUS_FEED_PUBLISH_COMPLETE"
    assert (dest / "MANIFEST.json").exists()
    db_files = list(dest.rglob("*.sqlite"))
    assert db_files == []
    secret_files = [p for p in dest.rglob("*") if p.name in SECRET_NAMES]
    assert secret_files == []


def test_verify_feed_passes_for_staging(tmp_path: Path):
    schema = feed_schema()
    items = build_feed_items()
    from scripts.doofus_shared_improvement_feed import build_blunder_bundle, mine_discoveries, publish_feed

    staging = tmp_path / "artifact_out"
    staging.mkdir()
    (staging / "FEED_SCHEMA.json").write_text(json.dumps(schema), encoding="utf-8")
    (staging / "MINED_DISCOVERIES_RAW.json").write_text("{}", encoding="utf-8")
    dest = tmp_path / "feed"
    publish_feed(
        staging_root=staging,
        dest_root=dest,
        items=items,
        schema=schema,
        mined=mine_discoveries(),
        blunder_bundle=build_blunder_bundle(items),
    )
    v = verify_feed(dest, items, schema, check_canonical=False)
    assert v["checks"]["feed_item_count_ok"] is True
    assert v["checks"]["no_db_files"] is True


def test_main_dry_run_writes_schema(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("DOOFUS_SHARED_FEED_DIR", str(tmp_path / "shared"))
    monkeypatch.setenv("DOOFUS_FEED_SKIP_TESTS", "1")
    proc = subprocess.run(
        [sys.executable, "scripts/doofus_shared_improvement_feed.py", "--dry-run"],
        cwd=WORKSPACE,
        capture_output=True,
        text=True,
        timeout=180,
    )
    out_dir = WORKSPACE / "artifacts" / "doofus" / "shared-improvement-feed-v1"
    assert (out_dir / "FEED_SCHEMA.json").exists()
    assert proc.returncode in (0, 1)
