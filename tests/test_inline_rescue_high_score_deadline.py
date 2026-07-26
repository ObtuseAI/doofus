"""Tests for inline rescue high-score defer behavior."""
from __future__ import annotations

import json
import sqlite3
import time

import pytest

from doofus.core import doofus_paths
from doofus.proof.high_score_rescue_loop import INLINE_RESCUE_EVENTS, run_inline_rescue


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
    monkeypatch.setattr("doofus.proof.high_score_miner_telemetry.EVENTS", state / "miner.jsonl")
    monkeypatch.setattr("doofus.proof.proof_builder_queue.queue_summary", lambda: {"queue_size": 0})
    monkeypatch.setattr("doofus.evolution.shadow_elite_retester.retest_shadow_elites", lambda **k: {"retested": 0})
    monkeypatch.setattr("doofus.proof.high_score_rescue_loop.retest_shadow_elites", lambda **k: {"retested": 0})
    monkeypatch.setattr(
        "doofus.evolution.shadow_elite_upgrade_queue.process_upgrade_batch",
        lambda **k: {"processed": 0},
    )
    monkeypatch.setattr(
        "doofus.proof.high_score_rescue_loop.process_upgrade_batch",
        lambda **k: {"processed": 0},
    )
    monkeypatch.setattr("doofus.evolution.elite_archive_maintainer.maintain_elite_archive", lambda **k: {})
    monkeypatch.setattr("doofus.proof.high_score_rescue_loop.maintain_elite_archive", lambda **k: {})
    monkeypatch.setattr("doofus.config.proof_builder_runtime_config.high_score_rescue_mode", lambda: True)
    monkeypatch.setattr("doofus.config.proof_builder_runtime_config.proof_builder_mode", lambda: False)
    return state


def test_inline_rescue_defers_when_miner_deadline_low(inline_env, monkeypatch):
    monkeypatch.setattr(
        "doofus.proof.high_score_rescue_loop.select_and_enqueue",
        lambda **k: {
            "enqueued": 0,
            "skipped": 0,
            "classification": "HIGH_SCORE_MINER_DEFERRED_DEADLINE",
            "timed_out": True,
        },
    )
    result = run_inline_rescue(baseline=0.9, generation=1640, max_seconds=30)
    assert result["classification"] == "INLINE_RESCUE_OK"
    assert result.get("timed_out") is False
    events = [json.loads(line) for line in (inline_env / "inline_rescue_events.jsonl").read_text().splitlines() if line]
    stages = [e.get("stage") for e in events]
    assert "inline_rescue_high_score_deferred" in stages or "high_score_enqueue_skipped_deadline" in stages


def test_inline_rescue_completes_when_miner_deferred(inline_env, monkeypatch):
    monkeypatch.setattr(
        "doofus.proof.high_score_rescue_loop.select_and_enqueue",
        lambda **k: {"enqueued": 0, "skipped": 0, "classification": "HIGH_SCORE_MINER_DEFERRED_DEADLINE", "timed_out": True},
    )
    started = time.monotonic()
    result = run_inline_rescue(baseline=0.9, generation=1640, max_seconds=10)
    assert time.monotonic() - started < 5
    assert result["classification"] == "INLINE_RESCUE_OK"
    end_events = [
        json.loads(line)
        for line in (inline_env / "inline_rescue_events.jsonl").read_text().splitlines()
        if line and json.loads(line).get("event_type") == "end"
    ]
    assert end_events


def test_inline_rescue_skips_high_score_on_low_budget(inline_env):
    result = run_inline_rescue(baseline=0.9, generation=1640, max_seconds=1)
    assert result["classification"] in {"INLINE_RESCUE_OK", "INLINE_RESCUE_TIMEOUT"}
