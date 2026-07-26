"""Tests for bounded high-score rejection miner deadline behavior."""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

from doofus.core import doofus_paths
from doofus.proof.high_score_rejection_miner import (
    MINER_DEADLINE_EXCEEDED,
    MINER_DEFERRED_DEADLINE,
    mine_high_score_rejections,
)


@pytest.fixture
def miner_db(tmp_path, monkeypatch):
    db = tmp_path / "metrics.sqlite"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE candidates (
            candidate_id TEXT PRIMARY KEY, parent_id TEXT, generation INTEGER, status TEXT,
            score_total REAL, rejection_reason TEXT, promotion_status TEXT, traits TEXT, mutation_type TEXT
        );
        CREATE TABLE arena_results (candidate_id TEXT, metric TEXT, value REAL);
        CREATE TABLE scores (candidate_id TEXT, metric TEXT, value REAL);
        """
    )
    for i in range(50):
        conn.execute(
            "INSERT INTO candidates VALUES (?,?,?,?,?,?,?,?,?)",
            (f"c{i}", "p", 1638, "rejected", 0.7 + i * 0.001, "proof_density_gate", "none", "{}", "m"),
        )
    conn.commit()
    conn.close()
    events = tmp_path / "high_score_miner_events.jsonl"
    monkeypatch.setattr(doofus_paths, "METRICS_DB", db)
    monkeypatch.setattr("doofus.proof.high_score_miner_telemetry.EVENTS", events)
    return db


def test_miner_checks_deadline_before_first_query(miner_db):
    result = mine_high_score_rejections(
        limit=10,
        deadline_monotonic=time.monotonic() - 1,
        db_path=miner_db,
        readonly=True,
    )
    assert result["classification"] == MINER_DEFERRED_DEADLINE
    assert result["timed_out"] is True


def test_miner_sql_has_hard_limit(miner_db):
    result = mine_high_score_rejections(limit=5, db_path=miner_db, readonly=True, enrich=False)
    assert len(result["top_100"]) <= 5


def test_miner_progress_abort_on_slow_query(miner_db, monkeypatch):
    import doofus.proof.high_score_rejection_miner as miner

    original = miner._execute_bounded_query

    def slow(conn, **kwargs):
        time.sleep(0.2)
        return original(conn, **kwargs)

    monkeypatch.setattr(miner, "_execute_bounded_query", slow)
    result = mine_high_score_rejections(
        limit=5,
        deadline_monotonic=time.monotonic() + 0.05,
        db_path=miner_db,
        readonly=True,
        enrich=False,
    )
    assert result["classification"] in {MINER_DEADLINE_EXCEEDED, MINER_DEFERRED_DEADLINE}


def test_miner_returns_empty_on_deadline(miner_db, monkeypatch):
    import doofus.proof.high_score_rejection_miner as miner

    def abort(conn, **kwargs):
        raise miner.MinerQueryAborted("test")

    monkeypatch.setattr(miner, "_execute_bounded_query", abort)
    result = mine_high_score_rejections(
        limit=5,
        deadline_monotonic=time.monotonic() + 60,
        db_path=miner_db,
        readonly=True,
    )
    assert result["classification"] == MINER_DEADLINE_EXCEEDED
    assert result["top_100"] == []


def test_miner_does_not_block_until_outer_watchdog(miner_db, monkeypatch):
    import doofus.proof.high_score_rejection_miner as miner

    def slow(conn, **kwargs):
        time.sleep(2.0)
        return original(conn, **kwargs)

    original = miner._execute_bounded_query
    monkeypatch.setattr(miner, "_execute_bounded_query", slow)
    started = time.monotonic()
    mine_high_score_rejections(
        limit=5,
        deadline_monotonic=time.monotonic() + 0.1,
        db_path=miner_db,
        readonly=True,
    )
    assert time.monotonic() - started < 1.5
