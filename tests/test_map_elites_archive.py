"""Tests for MAP-Elites archive."""
from __future__ import annotations

import json
import os
import sqlite3

import pytest

from doofus.core.metrics_db import connect_metrics_db
from doofus.evolution import map_elites_archive as mea


@pytest.fixture(autouse=True)
def isolated_archive(tmp_path, monkeypatch):
    arch = tmp_path / "map_elites_archive.json"
    monkeypatch.setattr(mea, "ARCHIVE_JSON", arch)
    monkeypatch.setenv("DOOFUS_MAP_ELITES_MODE", "1")
    yield


def test_insert_and_cell_key():
    c = {"candidate_id": "C1", "generation": 1, "mutation_type": "trait_mutation", "traits": ["a"]}
    scores = {"score_total": 0.8, "score_safety": 0.99}
    r = mea.insert(c, scores, arena_pass_rate=0.6)
    assert "cell_key" in r
    assert mea.load_all()


def test_occupancy_rate():
    assert mea.occupancy_rate() >= 0.0


def test_insert_can_reuse_existing_connection():
    candidate = {"candidate_id": "C_CONN", "generation": 7, "mutation_type": "trait_mutation", "traits": ["proof_density"]}
    scores = {"score_total": 0.81, "score_safety": 0.99}
    conn = connect_metrics_db()
    try:
        result = mea.insert(candidate, scores, arena_pass_rate=0.4, conn=conn)
        row = conn.execute(
            "SELECT candidate_id FROM map_elites_cells WHERE cell_key=?",
            (result["cell_key"],),
        ).fetchone()
        assert row is not None
        assert row[0] == "C_CONN"
    finally:
        conn.close()


def test_insert_with_caller_connection_skips_inline_repair_on_sql_error(monkeypatch):
    candidate = {"candidate_id": "C_ERR", "generation": 8, "mutation_type": "trait_mutation", "traits": ["proof_density"]}
    scores = {"score_total": 0.82, "score_safety": 0.99}
    calls = {"log_sqlite_health": 0, "reconcile": 0}

    def boom(*_args, **_kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(mea, "_upsert_sql", boom)
    monkeypatch.setattr(mea, "log_sqlite_health", lambda **_kwargs: calls.__setitem__("log_sqlite_health", calls["log_sqlite_health"] + 1))
    monkeypatch.setattr(
        "doofus.reports.sota_kpi_tracker.reconcile_map_elites_archive",
        lambda **_kwargs: calls.__setitem__("reconcile", calls["reconcile"] + 1),
    )

    conn = connect_metrics_db()
    try:
        result = mea.insert(candidate, scores, arena_pass_rate=0.5, conn=conn)
        assert result["sql_write_ok"] is False
        assert result["error_type"] == "OperationalError"
        assert "database is locked" in result["error_message_sanitized"]
        # Caller-owned connection remains usable.
        conn.execute("SELECT 1").fetchone()
    finally:
        conn.close()

    assert calls["log_sqlite_health"] == 0
    assert calls["reconcile"] == 0


def test_maintain_caps():
    for i in range(5):
        mea.insert(
            {"candidate_id": f"C{i}", "generation": i, "mutation_type": "trait_mutation"},
            {"score_total": 0.5 + i * 0.01, "score_safety": 0.99},
        )
    r = mea.maintain()
    assert r["cells"] <= r["cap"]
