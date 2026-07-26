from __future__ import annotations

import json
import os

from doofus.proof import high_score_rescue_loop as rescue
from doofus.supervisor.doofus_crash_recovery import load_checkpoint as load_supervisor_checkpoint
from doofus.supervisor.doofus_loop_runner import run_one_cycle


def test_inline_rescue_timeout_is_bounded_and_classified(monkeypatch, tmp_path):
    monkeypatch.setattr(rescue, "INLINE_RESCUE_EVENTS", tmp_path / "inline_rescue_events.jsonl")
    monkeypatch.setattr(rescue, "proof_builder_mode", lambda: True)
    monkeypatch.setattr(rescue, "high_score_rescue_mode", lambda: False)

    result = rescue.run_inline_rescue(baseline=0.5, generation=1637, max_seconds=0)

    rows = [
        json.loads(line)
        for line in rescue.INLINE_RESCUE_EVENTS.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert result["classification"] == "INLINE_RESCUE_TIMEOUT"
    assert result["timed_out"] is True
    assert result["elapsed_seconds"] < 0.5
    assert any(row["event_type"] == "timeout" for row in rows)


def test_inline_rescue_timeout_does_not_trigger_extra_model_call(monkeypatch):
    calls = {"provider": 0}
    monkeypatch.delenv("DOOFUS_FORCE_MODEL_DRY_RUN", raising=False)
    monkeypatch.delenv("DOOFUS_CYCLE_INIT_TIMEOUT_SECONDS", raising=False)
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.check_may_proceed", lambda: (True, "ok"))
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.proof_builder_mode", lambda: True)
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.prepare_cycle", lambda: {"candidate_count_next": 1})
    monkeypatch.setattr(
        "doofus.supervisor.doofus_loop_runner.generate_cycle_candidates",
        lambda generation, count=None: [
            {
                "candidate_id": "INLINE1",
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
        calls["provider"] += 1
        assert os.environ.get("DOOFUS_FORCE_MODEL_DRY_RUN") == "1"
        return {"classification": "DOOFUS_MODEL_DRY_RUN", "proposals": []}

    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.provider_propose_mutations", fake_provider)
    monkeypatch.setattr(
        "doofus.supervisor.doofus_loop_runner.run_inline_rescue",
        lambda **_kwargs: {
            "classification": "INLINE_RESCUE_TIMEOUT",
            "timed_out": True,
            "elapsed_seconds": 0.01,
            "active": True,
        },
    )
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
    assert calls["provider"] == 1
    assert load_supervisor_checkpoint()["phase"] == "complete"
