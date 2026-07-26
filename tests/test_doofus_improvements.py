"""Tests for audit fixes — lineage, arena, singleton."""
import pytest
import sqlite3
from doofus.mutation.candidate_generator import generate_cycle_candidates, generate_candidates
from doofus.mutation.mutation_engine import mutate_candidate
from doofus.scoring.arena_runner import run_local_arenas
from doofus.scoring.score_engine import score_candidate
from doofus.supervisor.process_singleton import acquire_singleton, release_singleton, read_singleton_pid
from doofus.supervisor.metrics_writer import log_mutation, log_arena_results
from doofus.core import doofus_paths
from doofus.core.doofus_state import init_db

def _db():
    """Always resolve patched METRICS_DB at call time."""
    return doofus_paths.METRICS_DB

@pytest.fixture(autouse=True)
def _isolate_db(tmp_path, monkeypatch):
    db = tmp_path / "test.sqlite"
    monkeypatch.setattr(doofus_paths, "METRICS_DB", db)
    init_db(db)

def _insert_parent(cid: str = "PARENT1") -> None:
    conn = sqlite3.connect(_db(), timeout=5.0)
    conn.execute(
        "INSERT OR REPLACE INTO candidates VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (cid, None, 1, "proof_density,replay_stability", "local", "agent_arcade,dry_replay",
         "promoted", 0.75, 1, 0.6, 0.5, 0.55, 0.5, None, "promoted", "2026-01-01"),
    )
    conn.execute("INSERT INTO promotions (candidate_id, created_at) VALUES (?,?)", (cid, "2026-01-01"))
    conn.commit()
    conn.close()

def test_mutate_sets_parent():
    c = generate_candidates(1, count=1, seed=1)[0]
    m = mutate_candidate(c)
    assert m["parent_id"] == c["candidate_id"]

def test_arena_runner_persists_shape():
    c = generate_candidates(1, count=1, seed=1)[0]
    s = score_candidate(c, 1)
    ar = run_local_arenas(c, s)
    assert len(ar) >= 2
    assert "pass" in ar[0]["result"] or "fail" in ar[0]["result"]

def test_lineage_cycle_with_promoted_parent(monkeypatch):
    monkeypatch.setattr("doofus.evolution.elite_parent_selector.load_elite_parents", lambda **k: [])
    monkeypatch.setattr("doofus.evolution.shadow_elite_parent_selector.load_shadow_elite_parents", lambda **k: [])
    monkeypatch.setattr("doofus.evolution.best_ever_ledger.get_best_ever", lambda: {})
    _insert_parent("P_LINEAGE")
    kids = generate_cycle_candidates(2, count=2, seed=1)
    assert any(c.get("parent_id") == "P_LINEAGE" for c in kids)

def test_singleton_lock(tmp_path, monkeypatch):
    monkeypatch.setattr("doofus.supervisor.process_singleton.STATE", tmp_path)
    assert acquire_singleton("test_svc") is True
    assert read_singleton_pid("test_svc") is not None
    release_singleton("test_svc")

def test_metrics_writer_mutation():
    conn = sqlite3.connect(_db(), timeout=5.0)
    log_mutation(conn, "C1", "trait_mutation")
    log_arena_results(conn, [{"candidate_id": "C1", "arena": "dry_replay", "result": "pass:0.6", "created_at": "2026-01-01"}])
    conn.commit()
    n = conn.execute("SELECT COUNT(*) FROM mutations").fetchone()[0]
    a = conn.execute("SELECT COUNT(*) FROM arena_results").fetchone()[0]
    conn.close()
    assert n == 1 and a == 1

def test_loop_writes_lineage_and_arena(monkeypatch):
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.check_may_proceed", lambda: (True, "ok"))
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.prepare_cycle", lambda: {"candidate_count_next": 1})
    # Force prequalification so the arena persistence path always runs — this
    # test verifies arena rows are written, not the prequal gate itself.
    monkeypatch.setattr(
        "doofus.supervisor.doofus_loop_runner.prequalify_candidate",
        lambda scores, baseline=0.5: {
            "eligible_for_expensive_scoring": True,
            "prequal_reason": "",
            "promotion_threshold": 0.72,
            "promotion_baseline": baseline,
            "replay_passed": True,
        },
    )
    monkeypatch.setattr(
        "doofus.supervisor.doofus_loop_runner.provider_propose_mutations",
        lambda _ctx: {"classification": "DOOFUS_MODEL_DRY_RUN", "proposals": []},
    )
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.after_cycle", lambda **kw: {})
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.after_compounding_cycle", lambda **kw: {})
    from doofus.supervisor.doofus_loop_runner import run_one_cycle
    _insert_parent("P_LOOP")
    run_one_cycle(dry_run=True)
    conn = sqlite3.connect(_db(), timeout=5.0)
    lineage = conn.execute("SELECT COUNT(*) FROM candidates WHERE parent_id IS NOT NULL").fetchone()[0]
    arenas = conn.execute("SELECT COUNT(*) FROM arena_results").fetchone()[0]
    muts = conn.execute("SELECT COUNT(*) FROM mutations").fetchone()[0]
    conn.close()
    assert lineage >= 1
    assert arenas >= 2
    assert muts >= 1
