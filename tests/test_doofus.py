"""Doofus test suite."""
import json
import os
import time
from pathlib import Path
import sqlite3
import pytest
from doofus.core import doofus_paths
from doofus.core.doofus_config import DoofusConfig
from doofus.core.doofus_state import init_db
from doofus.safety.on_off_switch import start, stop, emergency_stop, status, check_may_proceed
from doofus.mutation.candidate_generator import generate_candidates
from doofus.mutation.mutation_engine import mutate_candidate
from doofus.scoring.score_engine import score_candidate
from doofus.scoring.promotion_gate import evaluate_promotion
from doofus.safety.budget_guard import check_budget
from doofus.model_router.deepseek_v4_flash_adapter import DeepSeekV4FlashAdapter
from doofus.dashboard.dashboard_data import summary
from doofus.reports.doofus_report_builder import build_latest_run_report
from doofus.reports.doofus_shared_folder_exporter import export_shared_folder
from doofus.proof.high_score_rescue_loop import run_inline_rescue
from doofus.supervisor.doofus_loop_runner import run_one_cycle
from doofus.supervisor.doofus_crash_recovery import load_checkpoint as load_supervisor_checkpoint
from doofus.supervisor.heartbeat_watchdog import heartbeat_age_seconds

@pytest.fixture(autouse=True)
def _isolate_db(tmp_path, monkeypatch):
    db = tmp_path / "test.sqlite"
    monkeypatch.setattr("doofus.core.doofus_paths.METRICS_DB", db)
    monkeypatch.setattr("doofus.core.doofus_state.METRICS_DB", db)
    monkeypatch.setattr("doofus.safety.budget_guard.METRICS_DB", db)
    monkeypatch.setattr("doofus.dashboard.dashboard_data.METRICS_DB", db)
    init_db(db)

def test_doofus_paths():
    assert doofus_paths.CANONICAL_ROOT.name == "sai-auth-doofus"
    assert doofus_paths.ROOT.name == "doofus_test_root"

def test_doofus_config(monkeypatch):
    monkeypatch.setattr("doofus.core.doofus_env_loader.load_doofus_env", lambda: False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("DOOFUS_MODEL_PROVIDER", "openrouter")
    monkeypatch.setenv("DOOFUS_MODEL_NAME", "deepseek/deepseek-v4-flash")
    c = DoofusConfig.from_env()
    assert c.model_name == "deepseek/deepseek-v4-flash"
    assert c.model_mode in ("dry_run", "live")

def test_doofus_on_off_switch():
    doofus_paths.CONTROL.mkdir(parents=True, exist_ok=True)
    start()
    assert check_may_proceed()[0]
    stop()
    assert not check_may_proceed()[0]
    emergency_stop()
    assert not check_may_proceed()[0]

def test_doofus_metrics_schema():
    init_db()
    import sqlite3
    c = sqlite3.connect(doofus_paths.METRICS_DB)
    tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    c.close()
    assert "candidates" in tables and "heartbeats" in tables

def test_doofus_candidate_generator():
    cs = generate_candidates(1, count=2, seed=1)
    assert len(cs) == 2 and cs[0]["generation"] == 1

def test_doofus_mutation_engine():
    c = generate_candidates(1, count=1, seed=1)[0]
    m = mutate_candidate(c)
    assert m.get("parent_id") == c["candidate_id"]

def test_doofus_score_engine():
    c = generate_candidates(1, count=1, seed=1)[0]
    s = score_candidate(c, 1)
    assert 0 <= s["score_total"] <= 1

def test_doofus_promotion_gate():
    c = generate_candidates(1, count=1, seed=1)[0]
    s = score_candidate(c, 1)
    p = evaluate_promotion(c, s, 0.5)
    assert "promoted" in p

def test_doofus_budget_guard():
    b = check_budget(DoofusConfig.from_env())
    assert "ok" in b

def test_doofus_deepseek_adapter(monkeypatch):
    monkeypatch.setattr("doofus.core.doofus_env_loader.load_doofus_env", lambda: False)
    for k in ("OPENAI_API_KEY", "DOOFUS_OPENAI_API_KEY", "DOOFUS_OPENAI_MODEL", "DOOFUS_MODEL_PROVIDER"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("DOOFUS_MODEL_PROVIDER", "openrouter")
    monkeypatch.setenv("DOOFUS_MODEL_NAME", "deepseek/deepseek-v4-flash")
    from doofus.model_router.deepseek_v4_flash_adapter import DeepSeekV4FlashAdapter
    a = DeepSeekV4FlashAdapter.from_env()
    st = a.status()
    assert st["model"] == "deepseek/deepseek-v4-flash"
    r = a.propose_mutations({"generation": 1})
    assert "proposals" in r or "classification" in r

def test_doofus_dashboard_data():
    s = summary()
    assert "switch" in s

def test_doofus_report_builder():
    r = build_latest_run_report()
    assert r["foundry_proven"] is False

def test_doofus_shared_folder_exporter(tmp_path, monkeypatch):
    monkeypatch.setattr("doofus.reports.doofus_shared_folder_exporter.SHARED", tmp_path)
    e = export_shared_folder()
    assert (tmp_path / "DOOFUS-LOCAL-OPERATION-FINAL-REPORT.json").exists()

def test_doofus_supervisor_loop_once(monkeypatch):
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.check_may_proceed", lambda: (True, "ok"))
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.prepare_cycle", lambda: {"candidate_count_next": 1})
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.provider_propose_mutations", lambda _ctx: {"classification": "DOOFUS_MODEL_DRY_RUN", "proposals": []})
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.run_arenas", lambda *a, **k: [])
    monkeypatch.setattr(
        "doofus.supervisor.doofus_loop_runner._score_one_candidate",
        lambda conn, c, generation, baseline, dry_run, traits_before: (dict(c, status="rejected", rejection_reason="synthetic"), {}, 0, 0, 1, baseline),
    )
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.after_cycle", lambda **kw: {})
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.after_compounding_cycle", lambda **kw: {})
    r = run_one_cycle(dry_run=True)
    assert r["classification"] == "DOOFUS_CYCLE_COMPLETE"
    assert load_supervisor_checkpoint()["phase"] == "complete"


def test_doofus_nonlive_cycle_forces_model_dry_run(monkeypatch):
    seen = {}

    monkeypatch.delenv("DOOFUS_FORCE_MODEL_DRY_RUN", raising=False)
    monkeypatch.delenv("DOOFUS_CYCLE_INIT_TIMEOUT_SECONDS", raising=False)
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.check_may_proceed", lambda: (True, "ok"))
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.proof_builder_mode", lambda: False)
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.prepare_cycle", lambda: {"candidate_count_next": 1})
    monkeypatch.setattr(
        "doofus.supervisor.doofus_loop_runner.generate_cycle_candidates",
        lambda generation, count=None: [
            {
                "candidate_id": "NONLIVE1",
                "parent_id": None,
                "generation": generation,
                "traits": [],
                "mutation_type": "trait_mutation",
                "arena_targets": [],
                "status": "generated",
                "created_at": "2026-01-01T00:00:00+00:00",
            }
        ],
    )
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.filter_retired_parents", lambda candidates: candidates)
    def fake_provider(_ctx):
        seen["force_flag"] = os.environ.get("DOOFUS_FORCE_MODEL_DRY_RUN")
        return {"classification": "DOOFUS_MODEL_DRY_RUN", "proposals": []}

    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.provider_propose_mutations", fake_provider)
    monkeypatch.setattr(
        "doofus.supervisor.doofus_loop_runner._score_one_candidate",
        lambda conn, c, generation, baseline, dry_run, traits_before: (
            dict(c, status="rejected", rejection_reason="synthetic"),
            {},
            0,
            0,
            1,
            baseline,
        ),
    )
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.after_cycle", lambda **kw: {})
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.after_compounding_cycle", lambda **kw: {})

    result = run_one_cycle(dry_run=False, live_model_if_available=False)

    assert result["classification"] == "DOOFUS_CYCLE_COMPLETE"
    assert seen["force_flag"] == "1"
    assert "DOOFUS_FORCE_MODEL_DRY_RUN" not in os.environ
    assert load_supervisor_checkpoint()["phase"] == "complete"


def test_doofus_supervisor_loop_finalizes_timeout_checkpoint(monkeypatch):
    monkeypatch.setenv("DOOFUS_PHASE_TIMEOUT_CANDIDATE_GENERATION", "0.001")
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.check_may_proceed", lambda: (True, "ok"))
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.proof_builder_mode", lambda: False)

    def slow_prepare_cycle():
        time.sleep(0.02)
        return {"candidate_count_next": 1}

    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.prepare_cycle", slow_prepare_cycle)
    result = run_one_cycle(dry_run=False)
    checkpoint = load_supervisor_checkpoint()
    events = (doofus_paths.STATE / "supervisor_phase_events.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert result["classification"] == "DOOFUS_CYCLE_TIMEOUT"
    assert checkpoint["phase"] == "timeout_with_reason"
    assert checkpoint["timeout_phase"] == "candidate_generation"
    assert any(json.loads(line)["status"] == "timeout" for line in events if line.strip())


def test_doofus_inline_rescue_timeout_is_nonfatal(monkeypatch):
    monkeypatch.setenv("DOOFUS_PHASE_TIMEOUT_INLINE_RESCUE", "0.001")
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.check_may_proceed", lambda: (True, "ok"))
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.proof_builder_mode", lambda: True)
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.prepare_cycle", lambda: {"candidate_count_next": 1})
    monkeypatch.setattr(
        "doofus.supervisor.doofus_loop_runner.generate_cycle_candidates",
        lambda generation, count=None: [{
            "candidate_id": "C1",
            "parent_id": None,
            "generation": generation,
            "traits": [],
            "mutation_type": "trait_mutation",
            "arena_targets": [],
            "status": "generated",
            "created_at": "2026-01-01T00:00:00+00:00",
        }],
    )
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.filter_retired_parents", lambda candidates: candidates)
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.provider_propose_mutations", lambda _ctx: {"classification": "DOOFUS_MODEL_DRY_RUN", "proposals": []})
    monkeypatch.setattr(
        "doofus.supervisor.doofus_loop_runner._score_one_candidate",
        lambda conn, c, generation, baseline, dry_run, traits_before: (dict(c, status="rejected", rejection_reason="synthetic"), {}, 0, 0, 1, baseline),
    )
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.after_cycle", lambda **kw: {})
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.after_compounding_cycle", lambda **kw: {})

    def slow_inline_rescue(**_kwargs):
        time.sleep(0.02)
        return {"active": True, "elapsed_seconds": 0.02}

    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.run_inline_rescue", slow_inline_rescue)
    result = run_one_cycle(dry_run=False)
    checkpoint = load_supervisor_checkpoint()
    assert result["classification"] == "DOOFUS_CYCLE_COMPLETE"
    assert result["inline_rescue"]["classification"] == "INLINE_RESCUE_TIMEOUT"
    assert checkpoint["phase"] == "complete"


def test_doofus_scoring_timeout_is_preemptive(monkeypatch):
    monkeypatch.setenv("DOOFUS_PHASE_TIMEOUT_SCORING", "0.015")
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.check_may_proceed", lambda: (True, "ok"))
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.proof_builder_mode", lambda: False)
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.prepare_cycle", lambda: {"candidate_count_next": 3})
    monkeypatch.setattr(
        "doofus.supervisor.doofus_loop_runner.generate_cycle_candidates",
        lambda generation, count=None: [
            {
                "candidate_id": f"C{i}",
                "parent_id": None,
                "generation": generation,
                "traits": [],
                "mutation_type": "trait_mutation",
                "arena_targets": [],
                "status": "generated",
                "created_at": "2026-01-01T00:00:00+00:00",
            }
            for i in range(3)
        ],
    )
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.filter_retired_parents", lambda candidates: candidates)
    monkeypatch.setattr(
        "doofus.supervisor.doofus_loop_runner.provider_propose_mutations",
        lambda _ctx: {"classification": "DOOFUS_MODEL_DRY_RUN", "proposals": []},
    )

    def slow_score(conn, c, generation, baseline, dry_run, traits_before):
        time.sleep(0.01)
        return dict(c, status="rejected", rejection_reason="synthetic"), {}, 0, 0, 1, baseline

    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner._score_one_candidate", slow_score)
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.after_cycle", lambda **kw: {})
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.after_compounding_cycle", lambda **kw: {})

    result = run_one_cycle(dry_run=True)
    checkpoint = load_supervisor_checkpoint()
    events = (doofus_paths.STATE / "supervisor_phase_events.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert result["classification"] == "DOOFUS_CYCLE_TIMEOUT"
    assert checkpoint["phase"] == "timeout_with_reason"
    assert checkpoint["timeout_phase"] == "scoring"
    assert any(
        json.loads(line)["phase"] == "scoring" and json.loads(line)["status"] == "timeout"
        for line in events
        if line.strip()
    )


def test_doofus_low_score_candidate_skips_expensive_scoring(monkeypatch):
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.check_may_proceed", lambda: (True, "ok"))
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.proof_builder_mode", lambda: False)
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.prepare_cycle", lambda: {"candidate_count_next": 1})
    monkeypatch.setattr(
        "doofus.supervisor.doofus_loop_runner.generate_cycle_candidates",
        lambda generation, count=None: [
            {
                "candidate_id": "LOW1",
                "parent_id": None,
                "generation": generation,
                "traits": [],
                "mutation_type": "trait_mutation",
                "arena_targets": ["agent_arcade", "dry_replay"],
                "status": "generated",
                "created_at": "2026-01-01T00:00:00+00:00",
            }
        ],
    )
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.filter_retired_parents", lambda candidates: candidates)
    monkeypatch.setattr(
        "doofus.supervisor.doofus_loop_runner.provider_propose_mutations",
        lambda _ctx: {"classification": "DOOFUS_MODEL_DRY_RUN", "proposals": []},
    )
    monkeypatch.setattr(
        "doofus.supervisor.doofus_loop_runner.score_candidate",
        lambda *_args, **_kwargs: {
            "score_total": 0.31,
            "score_safety": 1.0,
            "score_replay": 0.50,
            "score_generalization": 0.40,
            "score_compounding": 0.40,
            "score_recursive_learning": 0.40,
            "proof_density_score": 0.45,
            "bloat_penalty": 0.0,
            "replay_stability_score": 0.50,
        },
    )
    monkeypatch.setattr(
        "doofus.supervisor.doofus_loop_runner.run_arenas",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("run_arenas should be skipped")),
    )
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.after_cycle", lambda **kw: {})
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.after_compounding_cycle", lambda **kw: {})

    result = run_one_cycle(dry_run=True)
    rows = [
        json.loads(line)
        for line in (doofus_paths.STATE / "scoring_step_events.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert result["classification"] == "DOOFUS_CYCLE_COMPLETE"
    assert any(row["scorer_name"] == "candidate_scoring" for row in rows)
    assert any(
        row["scorer_name"] == "arena_scoring"
        and row["substep"] == "run_arenas"
        and row["event_type"] == "skipped"
        for row in rows
    )


def test_doofus_supervisor_loop_finalizes_failed_checkpoint(monkeypatch):
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.check_may_proceed", lambda: (True, "ok"))
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.prepare_cycle", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    result = run_one_cycle(dry_run=True)
    checkpoint = load_supervisor_checkpoint()
    events = (doofus_paths.STATE / "supervisor_phase_events.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert result["classification"] == "DOOFUS_CYCLE_FAILED"
    assert checkpoint["phase"] == "failed_with_reason"
    assert checkpoint["error_type"] == "RuntimeError"
    assert any(json.loads(line)["status"] == "error" for line in events if line.strip())


def test_doofus_cycle_emits_progress_heartbeats(monkeypatch):
    heartbeats = []
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner._CYCLE_HEARTBEAT_SECONDS", 0.0)
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.check_may_proceed", lambda: (True, "ok"))
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.prepare_cycle", lambda: {"candidate_count_next": 1})
    monkeypatch.setattr(
        "doofus.supervisor.doofus_loop_runner.generate_cycle_candidates",
        lambda generation, count=None: [{
            "candidate_id": "C1",
            "parent_id": None,
            "generation": generation,
            "traits": [],
            "mutation_type": "trait_mutation",
            "arena_targets": [],
            "status": "generated",
            "created_at": "2026-01-01T00:00:00+00:00",
        }],
    )
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.filter_retired_parents", lambda candidates: candidates)
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.provider_propose_mutations", lambda _ctx: {"classification": "DOOFUS_MODEL_DRY_RUN", "proposals": []})
    monkeypatch.setattr(
        "doofus.supervisor.doofus_loop_runner._score_one_candidate",
        lambda conn, c, generation, baseline, dry_run, traits_before: (dict(c, status="rejected", rejection_reason="synthetic"), {}, 0, 0, 1, baseline),
    )
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.after_cycle", lambda **kw: {})
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.after_compounding_cycle", lambda **kw: {})
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.emit_heartbeat", lambda status, detail=None: heartbeats.append((status, detail or {})) or {"status": status})
    r = run_one_cycle(dry_run=True)
    assert r["classification"] == "DOOFUS_CYCLE_COMPLETE"
    progress_stages = [detail.get("stage") for status, detail in heartbeats if status == "cycle_progress"]
    assert "candidates_generated" in progress_stages
    assert "model_dry_run_complete" in progress_stages
    assert "scoring_complete" in progress_stages


def test_heartbeat_watchdog_ignores_runtime_manager_heartbeats(tmp_path, monkeypatch):
    db = tmp_path / "heartbeat.sqlite"
    heartbeats = tmp_path / "heartbeats"
    monkeypatch.setattr("doofus.core.doofus_paths.METRICS_DB", db)
    monkeypatch.setattr("doofus.core.doofus_state.METRICS_DB", db)
    monkeypatch.setattr("doofus.supervisor.heartbeat_watchdog.METRICS_DB", db)
    monkeypatch.setattr("doofus.supervisor.heartbeat_watchdog.HEARTBEATS", heartbeats)
    init_db(db)
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            "INSERT INTO heartbeats (status, detail, created_at) VALUES (?,?,?)",
            ("cycle_start", "{}", "2020-01-01T00:00:00+00:00"),
        )
        conn.execute(
            "INSERT INTO heartbeats (status, detail, created_at) VALUES (?,?,?)",
            ("runtime_manager_tick", "{}", "2030-01-01T00:00:00+00:00"),
        )
        conn.commit()
    finally:
        conn.close()
    age = heartbeat_age_seconds()
    assert age is not None
    assert age > 1000


def test_inline_rescue_reports_progress(monkeypatch):
    stages = []
    monkeypatch.setattr("doofus.proof.high_score_rescue_loop.proof_builder_mode", lambda: True)
    monkeypatch.setattr("doofus.proof.high_score_rescue_loop.high_score_rescue_mode", lambda: True)
    monkeypatch.setattr("doofus.proof.high_score_rescue_loop.select_and_enqueue", lambda **k: {"enqueued": 1, "skipped": 0})
    monkeypatch.setattr("doofus.proof.high_score_rescue_loop.retest_shadow_elites", lambda limit=10: {"retested": 1})
    monkeypatch.setattr(
        "doofus.proof.high_score_rescue_loop.process_upgrade_batch",
        lambda **k: {"processed": 1, "blocked": 1},
    )
    monkeypatch.setattr("doofus.proof.high_score_rescue_loop.maintain_elite_archive", lambda **k: {"elite_archive_count": 1})
    monkeypatch.setattr("doofus.proof.high_score_rescue_loop.inline_rescue_max_per_cycle", lambda: 2)

    def fake_batch(limit=10, baseline=0.5, progress_callback=None, deadline_monotonic=None):
        if progress_callback:
            progress_callback("proof_builder_item", {"completed": 1, "candidate_id": "C1", "outcome": "proof_ready"})
        return {"processed": 1, "successes": 1, "failures": 0, "results": []}

    monkeypatch.setattr("doofus.proof.high_score_rescue_loop.run_proof_builder_batch", fake_batch)

    result = run_inline_rescue(
        baseline=0.9378,
        generation=1640,
        progress_callback=lambda stage, detail: stages.append((stage, detail)),
    )

    assert result["active"] is True
    reported = [stage for stage, _detail in stages]
    assert "high_score_enqueue" in reported
    assert "shadow_retest" in reported
    assert "shadow_upgrade_start" in reported
    assert "shadow_upgrade" in reported
    assert "proof_builder_item" in reported
    assert "proof_builder_complete" in reported
