from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from doofus.dumbmoney import (
    AdversarialOperationsEvidenceV1,
    ArchiveDimensionV1,
    AutonomousResearchLoop,
    CandidateProposalV1,
    ConsequenceProfileV1,
    DailyExternalBudget,
    EconomicEvidenceV1,
    LineageArchive,
    MetricObservationV1,
    QualityDiversityArchive,
    ResearchCycleJournal,
    ResearchCycleRequestV1,
    ResearchMandateV1,
    ResearchObservationV1,
    StatisticalEvidenceV1,
    TrialExecutionV1,
    TrialRegistry,
    TrialStatus,
    content_hash,
)

NOW = datetime(2026, 7, 26, 21, 0, tzinfo=timezone.utc)


def digest(label: str) -> str:
    return content_hash({"label": label})


class FakeObservations:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def observe(self, request):
        self.calls.append(request.request_id)
        return ResearchObservationV1(
            observation_id=f"{request.cycle_id}:observation",
            mandate_hash=request.mandate_hash,
            as_of=request.as_of,
            source_refs=(digest(f"{request.cycle_id}:source"),),
            observation_artifact_ref=digest(f"{request.cycle_id}:observation-artifact"),
            point_in_time=True,
        )


class FakeGateway:
    def __init__(self, *, cost: int = 100_000) -> None:
        self.cost = cost
        self.calls: list[str] = []

    def propose(self, request):
        self.calls.append(request.request_id)
        return CandidateProposalV1(
            proposal_id=f"{request.cycle_id}:proposal",
            request_hash=request.content_hash,
            source_bundle_ref=digest(f"{request.cycle_id}:candidate-bundle"),
            origin_fingerprint=digest(f"{request.cycle_id}:origin"),
            parent_candidate_hashes=request.parent_candidate_hashes,
            mutation_operator="model_guided_fixture",
            behavior_cell=(
                ArchiveDimensionV1(name="domain", value="event_contract"),
                ArchiveDimensionV1(name="horizon", value="short"),
            ),
            rationale_artifact_ref=digest(f"{request.cycle_id}:rationale"),
            actual_model_cost_microusd=self.cost,
            generated_at=NOW + timedelta(seconds=1),
        )


class FakeRunner:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def run(self, request):
        self.calls.append(request.request_id)
        return TrialExecutionV1(
            request_hash=request.content_hash,
            status=TrialStatus.SUCCEEDED,
            started_at=NOW + timedelta(seconds=2),
            completed_at=NOW + timedelta(seconds=3),
            evaluator_ref=digest("sealed-evaluator"),
            metrics=(
                MetricObservationV1(
                    name="heldout_effect",
                    value="0.01",
                    unit="ratio",
                    sample_size=30,
                ),
            ),
            artifact_refs=(digest(f"{request.cycle_id}:trial-artifact"),),
            statistics=StatisticalEvidenceV1(
                independent_trial_count=2,
                holdout_sample_size=30,
                point_in_time_verified=True,
            ),
            economics=EconomicEvidenceV1(
                costs_complete=True,
                after_cost_edge_bps=1,
                turnover_included=True,
            ),
            operations=AdversarialOperationsEvidenceV1(
                sandbox_containment_passed=True,
                credential_scan_passed=True,
            ),
            quality_micros=100,
            novelty_micros=50,
        )


class CrashOnceRunner(FakeRunner):
    def run(self, request):
        self.calls.append(request.request_id)
        raise KeyboardInterrupt("simulated process loss after candidate journal")


class ErrorRunner(FakeRunner):
    def run(self, request):
        self.calls.append(request.request_id)
        raise RuntimeError("sandbox failed")


def mandate() -> ResearchMandateV1:
    return ResearchMandateV1(
        mandate_id="loop-mandate",
        objective="Autonomously falsify one candidate per bounded cycle.",
        hypotheses=("Candidate survives deterministic replay.",),
        evaluation_protocol_ref=digest("loop-protocol"),
        consequence=ConsequenceProfileV1(maximum_external_loss_cents=100),
        requested_by="test",
        created_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(days=1),
    )


def request(
    cycle_id: str,
    *,
    category="evidence_exploitation",
    maximum_model_cost_microusd: int = 200_000,
) -> ResearchCycleRequestV1:
    return ResearchCycleRequestV1(
        cycle_id=cycle_id,
        mandate=mandate(),
        budget_category=category,
        maximum_model_cost_microusd=maximum_model_cost_microusd,
        logical_started_at=NOW,
        trial_timeout_seconds=30,
    )


def components(tmp_path):
    lineage = LineageArchive(tmp_path / "lineage.jsonl")
    trials = TrialRegistry(tmp_path / "trials.jsonl")
    return {
        "cycle_journal": ResearchCycleJournal(tmp_path / "cycles.jsonl"),
        "budget": DailyExternalBudget(tmp_path / "budget.jsonl"),
        "lineage": lineage,
        "trials": trials,
        "archive": QualityDiversityArchive(tmp_path / "archive.jsonl", lineage=lineage),
    }


def make_loop(tmp_path, observations=None, gateway=None, runner=None, **kwargs):
    deps = components(tmp_path)
    observations = observations or FakeObservations()
    gateway = gateway or FakeGateway()
    runner = runner or FakeRunner()
    loop = AutonomousResearchLoop(
        **deps,
        observations=observations,
        model_gateway=gateway,
        trial_runner=runner,
        sealed_evaluator_ref=digest("sealed-evaluator"),
        **kwargs,
    )
    return loop, deps, observations, gateway, runner


def test_loop_runs_intake_budget_sandbox_courts_archive_and_retain(tmp_path) -> None:
    loop, deps, observations, gateway, runner = make_loop(tmp_path)
    result = loop.run_cycle(request("cycle-1"))

    assert result.status == "research_retained"
    assert result.governance is not None
    assert result.governance.automatic_action == "retain_research_only"
    assert result.eligible_for_live_promotion is False
    assert result.governance.eligible_for_live_promotion is False
    assert result.archive_admission_hash is not None
    assert len(observations.calls) == len(gateway.calls) == len(runner.calls) == 1
    assert deps["budget"].snapshot(NOW.date()).spent_microusd == 100_000
    assert len(deps["trials"].receipts()) == 1
    assert deps["trials"].receipts()[0].status is TrialStatus.SUCCEEDED
    stages = {event.stage for event in deps["cycle_journal"].events("cycle-1")}
    assert {
        "started",
        "observation_recorded",
        "proposal_request_recorded",
        "budget_reserved",
        "proposal_recorded",
        "budget_settled",
        "candidate_registered",
        "trial_recorded",
        "passport_issued",
        "verdict_recorded",
        "archive_recorded",
        "governance_recorded",
        "terminal",
    } <= stages
    assert all("promot" not in stage for stage in stages)


def test_terminal_cycle_replay_is_idempotent_and_calls_nothing_twice(tmp_path) -> None:
    loop, deps, observations, gateway, runner = make_loop(tmp_path)
    cycle = request("cycle-idempotent")
    first = loop.run_cycle(cycle)
    event_count = len(deps["cycle_journal"].events())
    second = loop.run_cycle(cycle)

    assert second == first
    assert len(deps["cycle_journal"].events()) == event_count
    assert len(observations.calls) == len(gateway.calls) == len(runner.calls) == 1
    assert len(deps["budget"].events()) == 2
    assert len(deps["trials"].receipts()) == 1


def test_restart_after_process_loss_reuses_proposal_budget_and_candidate(tmp_path) -> None:
    observations = FakeObservations()
    gateway = FakeGateway()
    crash_runner = CrashOnceRunner()
    loop, deps, _, _, _ = make_loop(
        tmp_path,
        observations=observations,
        gateway=gateway,
        runner=crash_runner,
    )
    cycle = request("cycle-restart")
    with pytest.raises(KeyboardInterrupt):
        loop.run_cycle(cycle)

    resumed = AutonomousResearchLoop(
        **deps,
        observations=observations,
        model_gateway=gateway,
        trial_runner=FakeRunner(),
        sealed_evaluator_ref=digest("sealed-evaluator"),
    )
    result = resumed.run_cycle(cycle)

    assert result.status == "research_retained"
    assert len(observations.calls) == 1
    assert len(gateway.calls) == 1
    assert len(deps["budget"].events()) == 2
    assert len(deps["lineage"].memberships()) == 1
    assert len(deps["trials"].receipts()) == 1


def test_trial_exception_becomes_visible_failed_receipt_and_quarantine(tmp_path) -> None:
    loop, deps, _, _, _ = make_loop(tmp_path, runner=ErrorRunner())
    result = loop.run_cycle(request("cycle-failed-trial"))
    receipt = deps["trials"].receipts()[0]
    passport_stage = deps["cycle_journal"].payload(
        "cycle-failed-trial", "passport_issued"
    )

    assert result.status == "quarantined"
    assert result.governance is not None
    assert result.governance.automatic_action == "quarantine"
    assert receipt.status is TrialStatus.FAILED
    assert receipt.failure_class == "sealed_runner_RuntimeError"
    assert receipt.content_hash in passport_stage["failed_trial_receipt_hashes"]
    assert result.archive_admission_hash is None


def test_stop_before_trial_records_aborted_attempt_and_quarantines(tmp_path) -> None:
    checks = {"count": 0}

    def stop_after_candidate() -> bool:
        checks["count"] += 1
        return checks["count"] >= 4

    loop, deps, _, _, runner = make_loop(tmp_path)
    result = loop.run_cycle(
        request("cycle-stop-after-candidate"),
        stop_requested=stop_after_candidate,
    )

    assert result.status == "quarantined"
    assert not runner.calls
    assert deps["trials"].receipts()[0].status is TrialStatus.ABORTED
    assert result.passport_hash is not None
    assert result.verdict_hash is not None


def test_deadline_before_intake_stops_without_external_calls(tmp_path) -> None:
    loop, deps, observations, gateway, runner = make_loop(
        tmp_path,
        monotonic_fn=lambda: 10.0,
    )
    result = loop.run_cycle(
        request("cycle-deadline"),
        deadline_monotonic=10.0,
    )

    assert result.status == "stopped"
    assert result.reasons == ("cycle_deadline_exhausted",)
    assert not observations.calls
    assert not gateway.calls
    assert not runner.calls
    assert not deps["budget"].events()


def test_budget_lane_hard_stop_prevents_model_and_trial(tmp_path) -> None:
    loop, _, _, gateway, runner = make_loop(tmp_path)
    result = loop.run_cycle(
        request(
            "cycle-budget-stop",
            category="novel_lineage",
            maximum_model_cost_microusd=2_000_001,
        )
    )

    assert result.status == "budget_exhausted"
    assert not gateway.calls
    assert not runner.calls


def test_gateway_cost_contract_violation_is_stopped_before_candidate(tmp_path) -> None:
    loop, deps, _, gateway, runner = make_loop(
        tmp_path,
        gateway=FakeGateway(cost=200_001),
    )
    result = loop.run_cycle(
        request("cycle-gateway-overrun", maximum_model_cost_microusd=200_000)
    )

    assert result.status == "budget_exhausted"
    assert result.reasons == ("model_gateway_exceeded_request_cost_ceiling",)
    assert gateway.calls
    assert not runner.calls
    assert not deps["lineage"].memberships()
    assert deps["budget"].snapshot(NOW.date()).spent_microusd == 200_000


def test_autonomous_run_has_explicit_max_cycle_bound(tmp_path) -> None:
    loop, _, observations, gateway, runner = make_loop(tmp_path)
    results = loop.run(
        (request("cycle-a"), request("cycle-b")),
        max_cycles=1,
    )

    assert len(results) == 1
    assert results[0].cycle_id == "cycle-a"
    assert len(observations.calls) == len(gateway.calls) == len(runner.calls) == 1
