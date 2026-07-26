"""Tests for shadow upgrade deadline and defer behavior."""
from __future__ import annotations

import json
import time

import pytest

from doofus.core import doofus_paths
from doofus.evolution.shadow_elite_upgrade_queue import process_upgrade_batch
from doofus.proof.inline_rescue_budget import SHADOW_UPGRADE_DEFERRED_DEADLINE


@pytest.fixture
def shadow_env(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    archive = state / "shadow_elite_archive.json"
    archive.write_text(
        json.dumps(
            [
                {"candidate_id": "S1", "score": 0.95, "generation": 1638, "upgraded": False},
                {"candidate_id": "S2", "score": 0.94, "generation": 1638, "upgraded": False},
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(doofus_paths, "STATE", state)
    monkeypatch.setattr(
        "doofus.evolution.shadow_elite_upgrade_queue.STATS",
        state / "shadow_elite_upgrade_stats.json",
    )
    monkeypatch.setattr(
        "doofus.evolution.shadow_upgrade_telemetry.EVENTS",
        state / "shadow_upgrade_events.jsonl",
    )
    monkeypatch.setattr(
        "doofus.evolution.shadow_elite_upgrade_queue.enqueue",
        lambda *a, **k: None,
    )
    return state


def test_shadow_upgrade_defers_when_deadline_low(shadow_env, monkeypatch):
    monkeypatch.setattr(
        "doofus.evolution.shadow_elite_upgrade_queue.run_process_one_guarded",
        lambda *a, **k: {"outcome": "proof_partial"},
    )
    result = process_upgrade_batch(
        limit=5,
        deadline_monotonic=time.monotonic() + 0.05,
        init_phase=True,
        generation=1640,
    )
    assert result.get("deferred") is True or result.get("classification") == SHADOW_UPGRADE_DEFERRED_DEADLINE


def test_shadow_upgrade_enforces_item_limit_in_init(shadow_env, monkeypatch):
    calls = []

    def guarded(cid, **k):
        calls.append(cid)
        return {"outcome": "proof_partial"}

    monkeypatch.setattr("doofus.evolution.shadow_elite_upgrade_queue.run_process_one_guarded", guarded)
    monkeypatch.setenv("DOOFUS_SHADOW_UPGRADE_INIT_ITEM_LIMIT", "1")
    result = process_upgrade_batch(
        limit=5,
        deadline_monotonic=time.monotonic() + 30,
        init_phase=True,
        generation=1640,
    )
    assert len(calls) <= 1
    assert result.get("processed", 0) <= 1


def test_shadow_upgrade_per_item_timeout(shadow_env, monkeypatch):
    monkeypatch.setenv("DOOFUS_SHADOW_UPGRADE_MAX_ITEM_SECONDS", "0.5")

    def slow_guarded(cid, **k):
        time.sleep(1.0)
        return {"outcome": "proof_timeout"}

    monkeypatch.setattr("doofus.evolution.shadow_elite_upgrade_queue.run_process_one_guarded", slow_guarded)
    started = time.monotonic()
    result = process_upgrade_batch(
        limit=1,
        deadline_monotonic=time.monotonic() + 30,
        init_phase=True,
        generation=1640,
    )
    assert time.monotonic() - started < 10
    assert result.get("processed", 0) <= 1


def test_shadow_upgrade_emits_telemetry(shadow_env, monkeypatch):
    monkeypatch.setattr(
        "doofus.evolution.shadow_elite_upgrade_queue.run_process_one_guarded",
        lambda *a, **k: {"outcome": "proof_partial"},
    )
    process_upgrade_batch(
        limit=1,
        deadline_monotonic=time.monotonic() + 30,
        init_phase=True,
        generation=1640,
    )
    events_path = shadow_env / "shadow_upgrade_events.jsonl"
    assert events_path.exists()
    events = [json.loads(line) for line in events_path.read_text().splitlines() if line]
    steps = {e.get("step") for e in events}
    assert "shadow_upgrade_start" in steps
    assert "shadow_upgrade_end" in steps or "shadow_upgrade_deferred" in steps


def test_dry_run_defers_without_proof(shadow_env):
    result = process_upgrade_batch(
        limit=5,
        deadline_monotonic=time.monotonic() + 30,
        init_phase=True,
        generation=1640,
        run_proof=False,
    )
    assert result.get("deferred") is True
    assert result.get("classification") == SHADOW_UPGRADE_DEFERRED_DEADLINE
    assert result.get("processed") == 0
