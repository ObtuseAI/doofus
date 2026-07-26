"""Integration coverage for metacognitive prediction, control, and evidence gates."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from doofus.arenas.metacognitive.evaluator import run_metacognitive_arenas
from doofus.core.atomic_json import save_json
from doofus.dashboard.live_metacognition_charts import build_metacognition_charts
from doofus.evolution.evolution_pressure_mode import prepare_cycle
from doofus.meta.aevolve.algorithm_selector import select_algorithms_for_cycle
from doofus.metacognition.calibration import (
    CalibrationObservation,
    summarize_calibration,
)
from doofus.metacognition.confidence import aggregate_confidence
from doofus.metacognition.causal_monitor import assess_causal_gain
from doofus.metacognition.controller import (
    complete_metacognitive_cycle,
    get_active_control,
    get_metacognitive_snapshot,
    prepare_metacognitive_cycle,
)
from doofus.metacognition.meta_evolution import evolve_meta_policy
from doofus.metacognition.predictions import prediction_row
from doofus.metacognition.fsf_contract import (
    BoundedMutationMandate,
    MutationProposalEnvelope,
    PROTECTED_AUTHORITY_SURFACES,
    validate_proposal,
)
from doofus.metacognition.runtime_control import active_arena_limit, active_control_file


def test_model_self_confidence_is_not_authoritative() -> None:
    confidence = aggregate_confidence(0.95, 0.45, 0.30)
    assert confidence.model == 0.95
    assert confidence.final_control < 0.50


def test_single_observation_does_not_claim_strong_causality() -> None:
    causal = assess_causal_gain(0.03, [0.03], True, True)
    assert causal.replication_count == 1
    assert causal.causal_confidence <= 0.35


def test_calibration_metrics_score_falsifiable_predictions() -> None:
    observations = [
        CalibrationObservation(
            predicted_probability=0.80,
            actual_outcome=True,
            predicted_fitness=0.70,
            actual_fitness=0.72,
            interval_low=0.65,
            interval_high=0.75,
            recommended_action="continue",
        ),
        CalibrationObservation(
            predicted_probability=0.20,
            actual_outcome=False,
            predicted_fitness=0.50,
            actual_fitness=0.45,
            interval_low=0.40,
            interval_high=0.55,
            recommended_action="abstain",
        ),
    ]
    summary = summarize_calibration(observations)
    assert round(summary.brier_score, 6) == 0.04
    assert summary.prediction_interval_coverage == 1.0
    assert summary.abstention_quality == 1.0


def test_shadow_cycle_records_prediction_before_outcome(monkeypatch) -> None:
    monkeypatch.setenv("DOOFUS_METACOGNITION_MODE", "shadow")
    prepared = prepare_metacognitive_cycle("doofus", True, True)
    prediction_id = str(prepared["prediction_id"])
    before = prediction_row(prediction_id)
    assert before["resolved_at"] is None
    assert prepared["decision"]["authorized"] is False
    assert get_active_control() is None

    baseline = float(before["baseline_fitness"])
    evaluated = complete_metacognitive_cycle(
        prepared,
        {
            "classification": "DOOFUS_CYCLE_COMPLETE",
            "baseline_score": min(1.0, baseline + 0.01),
            "generation": int(before["generation"]),
            "promoted": 1,
        },
    )
    after = prediction_row(prediction_id)
    assert evaluated["classification"] == "METACOGNITIVE_OUTCOME_EVALUATED"
    assert after["resolved_at"] is not None
    assert float(after["actual_gain"]) > 0.0


def test_bounded_controller_never_mutates_authority_surface(monkeypatch) -> None:
    monkeypatch.setenv("DOOFUS_METACOGNITION_MODE", "bounded")
    prepared = prepare_metacognitive_cycle("doofus", True, True)
    decision = prepared["decision"]
    assert decision["authorized_allocation"]["stronger_model_escalations"] == 0
    assert decision["authorized_allocation"]["candidates"] <= 48
    snapshot = get_metacognitive_snapshot("doofus")
    assert all(snapshot["immutable_authority_boundary"].values())


def test_bounded_control_reaches_existing_candidate_and_strategy_interfaces(monkeypatch) -> None:
    monkeypatch.setenv("DOOFUS_METACOGNITION_MODE", "bounded")
    save_json(
        active_control_file(),
        {
            "active": True,
            "decision": {
                "authorized": True,
                "recommendation": "diversify",
                "algorithm_portfolio": {"gene_crossover": 1.0},
                "authorized_allocation": {
                    "candidates": 12,
                    "arena_repetitions": 2,
                    "early_termination_allowed": False,
                },
            },
        },
    )
    pressure = prepare_cycle()
    algorithms = select_algorithms_for_cycle(5, seed=7)
    assert pressure["candidate_count_next"] == 12
    assert algorithms == ["gene_crossover"] * 5
    assert active_arena_limit(4) == 2


def test_fsf_contract_keeps_blunder_authority_external(tmp_path) -> None:
    mandate = BoundedMutationMandate(
        mandate_id="mandate-1",
        target_id="doofus",
        isolated_worktree=str(tmp_path),
        allowed_relative_paths=("doofus/metacognition/state.py",),
        forbidden_authority_surfaces=PROTECTED_AUTHORITY_SURFACES,
        maximum_candidates=4,
        maximum_provider_calls=1,
        required_evidence=("prediction-ledger", "arena-results"),
        expires_at_utc=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        operator_approved=True,
    )
    proposal = MutationProposalEnvelope(
        mandate_id="mandate-1",
        target_id="doofus",
        strategy_id="adaptive_search",
        candidate_ids=("c1",),
        prediction_ids=("p1",),
        requested_paths=("doofus/metacognition/state.py",),
        evidence_refs=("prediction-ledger", "arena-results"),
        metacognitive_policy_id="metacognitive_cortex_v1",
    )
    valid, violations = validate_proposal(mandate, proposal)
    assert valid is True
    assert violations == ()


def test_research_arenas_and_meta_evolution_remain_experimental(monkeypatch) -> None:
    monkeypatch.setenv("DOOFUS_METACOGNITION_MODE", "shadow")
    arenas = run_metacognitive_arenas("doofus")
    meta = evolve_meta_policy("doofus")
    assert arenas["experimental"] is True
    assert arenas["all_research_claims_pass"] is False
    assert meta["classification"] == "META_METACOGNITION_INSUFFICIENT_HOLDOUT_EVIDENCE"


def test_metacognition_dashboard_charts_build() -> None:
    charts = build_metacognition_charts()
    assert "reliability" in charts
    assert "predicted_actual_fitness" in charts
    assert all(hasattr(figure, "update_layout") for figure in charts.values())
