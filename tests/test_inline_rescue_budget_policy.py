"""Tests for inline rescue budget policy and shadow upgrade defer integration."""
from __future__ import annotations

import json
import sqlite3
import time

import pytest

from doofus.core import doofus_paths
from doofus.proof.high_score_rescue_loop import run_inline_rescue
from doofus.proof.inline_rescue_budget import (
    INLINE_RESCUE_SHADOW_UPGRADE_DEFERRED,
    SHADOW_UPGRADE_DEFERRED_DEADLINE,
    policy_snapshot,
    should_defer_shadow_upgrade,
)


@pytest.fixture
def inline_env(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    db = tmp_path / "metrics.sqlite"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE candidates (
            candidate_id TEXT PRIMARY KEY, parent_id TEXT, generation INTEGER, status TEXT,
            score_total REAL, rejection_reason TEXT, promotion_status TEXT, traits TEXT, mutation_type TEXT
        );
        """
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(doofus_paths, "STATE", state)
    monkeypatch.setattr(doofus_paths, "METRICS_DB", db)
    events_path = state / "inline_rescue_events.jsonl"
    monkeypatch.setattr("doofus.proof.high_score_rescue_loop.INLINE_RESCUE_EVENTS", events_path)
    monkeypatch.setattr("doofus.proof.proof_builder_queue.queue_summary", lambda: {"queue_size": 0})
    monkeypatch.setattr("doofus.evolution.shadow_elite_retester.retest_shadow_elites", lambda **k: {"retested": 0})
    monkeypatch.setattr("doofus.proof.high_score_rescue_loop.retest_shadow_elites", lambda **k: {"retested": 0})
    monkeypatch.setattr("doofus.evolution.elite_archive_maintainer.maintain_elite_archive", lambda **k: {})
    monkeypatch.setattr("doofus.proof.high_score_rescue_loop.maintain_elite_archive", lambda **k: {})
    monkeypatch.setattr("doofus.config.proof_builder_runtime_config.high_score_rescue_mode", lambda: False)
    monkeypatch.setattr("doofus.config.proof_builder_runtime_config.proof_builder_mode", lambda: False)
    return state


def test_budget_policy_snapshot():
    snap = policy_snapshot()
    assert snap["init_watchdog_seconds"] == 180
    assert snap["shadow_upgrade_max_seconds"] == 30
    assert snap["candidate_gen_reserve_seconds"] == 60


def test_should_defer_when_budget_low():
    defer, reason = should_defer_shadow_upgrade(time.monotonic() + 0.05, init_phase=True)
    assert defer is True
    assert reason


def test_inline_rescue_completes_after_shadow_defer(inline_env, monkeypatch):
    monkeypatch.setattr(
        "doofus.evolution.shadow_elite_upgrade_queue.process_upgrade_batch",
        lambda **k: {
            "processed": 0,
            "deferred": True,
            "classification": SHADOW_UPGRADE_DEFERRED_DEADLINE,
        },
    )
    started = time.monotonic()
    result = run_inline_rescue(baseline=0.72, generation=1640, max_seconds=30, init_phase=True)
    assert time.monotonic() - started < 5
    assert result["classification"] == "INLINE_RESCUE_OK"
    assert result.get("timed_out") is False


def test_inline_rescue_emits_shadow_upgrade_deferred_telemetry(inline_env, monkeypatch):
    monkeypatch.setattr(
        "doofus.evolution.shadow_elite_upgrade_queue.process_upgrade_batch",
        lambda **k: {
            "processed": 0,
            "deferred": True,
            "classification": SHADOW_UPGRADE_DEFERRED_DEADLINE,
        },
    )
    run_inline_rescue(baseline=0.72, generation=1640, max_seconds=30, init_phase=True)
    events = [json.loads(line) for line in (inline_env / "inline_rescue_events.jsonl").read_text().splitlines() if line]
    stages = [e.get("stage") for e in events]
    assert "inline_rescue_shadow_upgrade_deferred" in stages


def test_init_phase_caps_inline_rescue_seconds(inline_env, monkeypatch):
    monkeypatch.setattr(
        "doofus.evolution.shadow_elite_upgrade_queue.process_upgrade_batch",
        lambda **k: {"processed": 0, "deferred": True, "classification": SHADOW_UPGRADE_DEFERRED_DEADLINE},
    )
    result = run_inline_rescue(baseline=0.72, generation=1640, max_seconds=180, init_phase=True)
    assert result["elapsed_seconds"] < 120
