"""Tests for GEPA trace collector and prompt store."""
from __future__ import annotations

import pytest

from doofus.core.metrics_db import connect_metrics_db
from doofus.meta.gepa import trace_collector as tc
from doofus.meta.gepa import prompt_store as ps
from doofus.meta.gepa.prompt_evolver import run_batch


@pytest.fixture(autouse=True)
def isolated_gepa(tmp_path, monkeypatch):
    monkeypatch.setattr(tc, "TRACE_DIR", tmp_path / "gepa")
    monkeypatch.setattr(tc, "TRACE_JSONL", tmp_path / "gepa" / "traces.jsonl")
    monkeypatch.setattr(ps, "PROMPT_DIR", tmp_path / "gepa" / "prompts")
    monkeypatch.setenv("DOOFUS_GEPA_MODE", "1")
    monkeypatch.setenv("DOOFUS_GEPA_MIN_TRACES", "2")
    yield


def test_record_and_sample_traces():
    tc.record_trace(cycle_id=1, candidate_id="C1", rejection_reason="proof_density_gate", score_delta=-0.05)
    tc.record_trace(cycle_id=1, candidate_id="C2", score_delta=0.1)
    traces = tc.sample_traces(limit=10)
    assert len(traces) == 2


def test_record_trace_can_reuse_existing_connection():
    conn = connect_metrics_db()
    try:
        tc.record_trace(cycle_id=7, candidate_id="C7", score_delta=0.07, conn=conn)
        conn.commit()
    finally:
        conn.close()
    assert tc.count_traces_since() == 1


def test_prompt_store_version():
    active = ps.get_active("mutation")
    assert "Doofus" in active
    ps.save_version("mutation", active + " test", fitness=0.5, activate=True)
    assert ps.get_active_hash("mutation")


def test_gepa_batch_force():
    for i in range(3):
        tc.record_trace(cycle_id=i, candidate_id=f"C{i}", score_delta=0.01)
    r = run_batch(force=True)
    assert r["classification"] in ("GEPA_BATCH_COMPLETE", "GEPA_BATCH_NO_CHANGE")
