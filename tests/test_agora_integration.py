"""Integration coverage for attended Agora missions and constitutional boundaries."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from doofus.agora.config import (
    load_provider_nodes,
    load_roles,
    load_security_policy,
    load_terms_sources,
    load_topologies,
)
from doofus.agora.contracts import (
    ContextClass,
    DecisionAction,
    ExecutionMode,
    MissionStage,
    TermsDecision,
    TermsStatus,
)
from doofus.agora.errors import (
    AgoraPolicyError,
    ArtifactIntegrityError,
    ContextExportBlockedError,
    ResponseImportError,
    TermsReviewRequiredError,
)
from doofus.agora.capture import import_response
from doofus.agora.debate import build_idea_cards, cluster_artifacts
from doofus.agora.evidence import PriorArtSearch, RetrievedSource
from doofus.agora.mission import CONSTITUTION
from doofus.agora.providers import assert_automation_allowed, route_providers
from doofus.agora.problem_foundry import (
    collect_problem_portfolio,
    problem_solution_tournament,
)
from doofus.agora.service import AgoraService
from doofus.agora.storage import AgoraRepository
from doofus.core.doofus_events import utc_now

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "doofus" / "agora" / "policy"
FIXTURES = ROOT / "tests" / "fixtures" / "agora"


class FixtureEvidenceFabric:
    """Deterministic keyless connector for the offline attended acceptance mission."""

    def fetch_url(self, url: str) -> RetrievedSource:
        payload = f"fixture evidence for {url}".encode("utf-8")
        return RetrievedSource(
            url=url,
            status_code=200,
            content_type="text/plain",
            payload=payload,
            sha256=hashlib.sha256(payload).hexdigest(),
        )

    def search_prior_art(self, query: str) -> PriorArtSearch:
        return PriorArtSearch(
            query=query,
            repository_results=(),
            literature_results=(),
            failures=(),
        )


def _service(tmp_path: Path) -> AgoraService:
    repository = AgoraRepository(
        database_path=tmp_path / "agora.sqlite",
        vault_root=tmp_path / "vault",
    )
    repository.initialize()
    return AgoraService(
        repository=repository,
        providers=load_provider_nodes(POLICY),
        roles=load_roles(POLICY),
        topologies=load_topologies(POLICY),
        security_policy=load_security_policy(POLICY),
        terms_sources=load_terms_sources(POLICY),
        evidence_fabric=FixtureEvidenceFabric(),
        config_dir=POLICY,
        runtime_root=tmp_path,
    )


def _mission_payload(context_class: str = "PUBLIC") -> dict[str, object]:
    return {
        "mission_type": "invention",
        "objective": "Invent a deterministic identity mechanism with proof receipts.",
        "decision_to_inform": "Whether to admit the mechanism to bounded experiments.",
        "target_project": "doofus",
        "context": "This is public fixture context for a provider-free acceptance mission.",
        "context_class": context_class,
        "known_evidence": ("JSON scalar equality is deterministic.",),
        "hard_constraints": (
            "Preserve every existing promotion, rollback, budget, and safety gate.",
        ),
        "forbidden_actions": (
            "No browser automation, repository mutation, credentials, or live execution.",
        ),
        "success_metrics": ("Exact differential output equality.",),
        "falsification_conditions": ("Any mismatch or sandbox escape attempt.",),
        "open_questions": ("What is the cheapest decisive experiment?",),
        "candidate_test_cases": (
            {"input": {"value": 0}, "expected": 0},
            {"input": {"value": 1}, "expected": 1},
            {"input": {"value": -1}, "expected": -1},
        ),
        "benchmark_baseline_score": 1000.0,
        "maximum_nodes": 6,
        "maximum_rounds": 3,
        "topology_id": "frontier_hexagon",
    }


def _fixture_response(provider_id: str) -> str:
    return (FIXTURES / f"{provider_id}.md").read_text(encoding="utf-8")


def _import_pending(service: AgoraService, mission_id: str) -> None:
    imported = {response.packet_id for response in service.responses(mission_id)}
    for packet in service.packets(mission_id):
        if packet.packet_id not in imported:
            service.import_response_text(
                packet.packet_id,
                _fixture_response(packet.provider_id),
            )


def _sandbox_available() -> bool:
    if shutil.which("wsl.exe") is None:
        return False
    result = subprocess.run(
        [
            "wsl.exe",
            "-d",
            "Ubuntu",
            "--",
            "sh",
            "-lc",
            "command -v bwrap && command -v prlimit && command -v python3",
        ],
        capture_output=True,
        check=False,
        timeout=15.0,
    )
    return result.returncode == 0


def test_context_classification_and_sanitation_fail_closed(tmp_path: Path) -> None:
    service = _service(tmp_path)
    missing_class = _mission_payload()
    missing_class.pop("context_class")
    with pytest.raises(ContextExportBlockedError, match="SECRET"):
        service.create_mission(missing_class, operator_approved=False)
    explicit_null_class = _mission_payload()
    explicit_null_class["context_class"] = None
    with pytest.raises(ContextExportBlockedError, match="SECRET"):
        service.create_mission(explicit_null_class, operator_approved=False)

    public_sensitive = _mission_payload()
    public_sensitive["context"] = "Contact private.person@example.com before exporting."
    with pytest.raises(ContextExportBlockedError, match="PUBLIC context contains"):
        service.create_mission(public_sensitive, operator_approved=False)

    internal = _mission_payload(ContextClass.SANITIZED_INTERNAL.value)
    internal["context"] = "Contact private.person@example.com before exporting."
    with pytest.raises(ContextExportBlockedError, match="operator approval"):
        service.create_mission(internal, operator_approved=False)
    mission = service.create_mission(internal, operator_approved=True)
    assert "[REDACTED:email]" in mission.context
    assert "private.person@example.com" not in mission.context


def test_terms_automation_requires_every_independent_gate(tmp_path: Path) -> None:
    service = _service(tmp_path)
    attended = service.providers[0]
    autonomous = attended.model_copy(
        update={
            "execution_mode": ExecutionMode.AUTONOMOUS_ALLOWED,
            "automated_submit_allowed": True,
            "automated_extract_allowed": True,
        }
    )
    with pytest.raises(AgoraPolicyError, match="no separately registered"):
        assert_automation_allowed(
            autonomous,
            service.repository,
            adapter_registered=False,
            operator_approved=True,
            budget_gates_passed=True,
        )
    with pytest.raises(TermsReviewRequiredError, match="no recorded terms"):
        assert_automation_allowed(
            autonomous,
            service.repository,
            adapter_registered=True,
            operator_approved=True,
            budget_gates_passed=True,
        )
    service.repository.record_terms_decision(
        TermsDecision(
            provider_id=autonomous.provider_id,
            source_url="https://example.com/terms",
            document_sha256="a" * 64,
            reviewed_at=utc_now(),
            reviewer="fixture-operator",
            status=TermsStatus.CURRENT,
            automated_submit_allowed=True,
            automated_extract_allowed=True,
            notes="Fixture-only explicit decision.",
        )
    )
    with pytest.raises(AgoraPolicyError, match="budget gates"):
        assert_automation_allowed(
            autonomous,
            service.repository,
            adapter_registered=True,
            operator_approved=True,
            budget_gates_passed=False,
        )
    assert_automation_allowed(
        autonomous,
        service.repository,
        adapter_registered=True,
        operator_approved=True,
        budget_gates_passed=True,
    )


def test_vault_tamper_and_malformed_import_are_rejected(tmp_path: Path) -> None:
    service = _service(tmp_path)
    digest, path = service.repository.store_blob("fixture", b"immutable")
    path.write_bytes(b"tampered")
    with pytest.raises(ArtifactIntegrityError, match="hash mismatch"):
        service.repository.read_blob(digest)

    mission = service.create_mission(_mission_payload(), operator_approved=False)
    packet = service.packets(mission.mission_id)[0]
    with pytest.raises(ResponseImportError, match="too short"):
        service.import_response_text(packet.packet_id, "No.")


def test_routing_is_deterministic_and_constitution_is_immutable(tmp_path: Path) -> None:
    service = _service(tmp_path)
    roles = load_roles(POLICY)
    topology = load_topologies(POLICY)["frontier_hexagon"]
    required_roles = tuple(topology["divergence_roles"])
    first = route_providers(
        service.providers,
        roles,
        required_roles,
        "invention",
        "frontier_hexagon",
        6,
        742391,
        service.repository,
    )
    second = route_providers(
        service.providers,
        roles,
        required_roles,
        "invention",
        "frontier_hexagon",
        6,
        742391,
        service.repository,
    )
    assert [(provider.provider_id, role) for provider, role in first] == [
        (provider.provider_id, role) for provider, role in second
    ]
    assert len({provider.provider_id for provider, _ in first}) == 6

    mission = service.create_mission(_mission_payload(), operator_approved=False)
    packet = service.packets(mission.mission_id)[0]
    assert packet.prompt_text.startswith(CONSTITUTION)
    assert "promotion thresholds" in packet.prompt_text
    with pytest.raises(ValidationError, match="frozen"):
        packet.prompt_text = "replace the constitution"


def test_blind_debate_hides_identity_and_preserves_minority(tmp_path: Path) -> None:
    service = _service(tmp_path)
    mission = service.create_mission(_mission_payload(), operator_approved=False)
    _import_pending(service, mission.mission_id)
    service.advance_round(mission.mission_id)
    critique_packets = [
        packet
        for packet in service.packets(mission.mission_id)
        if packet.round_type.value == "CRITIQUE"
    ]
    provider_by_artifact = {
        response.artifact_id: response.provider_id
        for response in service.responses(mission.mission_id)
    }
    for packet in critique_packets:
        assert packet.provider_id not in packet.prompt_text.lower()
        assert "Proposal " in packet.prompt_text
        assert "Provider identities are intentionally withheld" in packet.prompt_text
        assert all(
            provider_by_artifact[artifact_id] != packet.provider_id
            for artifact_id in packet.source_artifact_ids
        )
    _import_pending(service, mission.mission_id)
    service.advance_round(mission.mission_id)
    _import_pending(service, mission.mission_id)
    result = service.advance_round(mission.mission_id)
    cards = service.idea_cards(mission.mission_id)
    assert result["minority_count"] >= 1
    assert any(card.minority_preserved for card in cards)
    assert service.current_stage(mission.mission_id) is MissionStage.VERIFYING


def test_correlated_majority_does_not_erase_distinct_minority(tmp_path: Path) -> None:
    service = _service(tmp_path)
    mission = service.create_mission(_mission_payload(), operator_approved=False)
    packets = service.packets(mission.mission_id)[:4]
    majority = (
        "1. Use one shared majority mechanism based on deterministic direct pass-through.\n"
        "2. The mechanism returns each supplied value unchanged under a pure function contract.\n"
        "3. Its strongest failure is hidden coercion of boundary values.\n"
        "4. Falsify it with exact differential equality and negative inputs.\n"
        "5. Confidence: 0.90"
    )
    minority = (
        "1. Preserve a mechanistically distinct checksum receipt around the returned value.\n"
        "2. Canonical receipt verification detects tampering without changing the output contract.\n"
        "3. Its strongest failure is noncanonical serialization across implementations.\n"
        "4. Falsify it by corrupting one frozen receipt and requiring explicit rejection.\n"
        "5. Confidence: 0.61"
    )
    artifacts = tuple(
        import_response(
            packet,
            majority if index < 3 else minority,
            service.repository,
        )
        for index, packet in enumerate(packets)
    )
    clusters = cluster_artifacts(artifacts, similarity_threshold=0.54)
    assert len({clusters[artifact.artifact_id] for artifact in artifacts[:3]}) == 1
    assert clusters[artifacts[3].artifact_id] != clusters[artifacts[0].artifact_id]
    cards = build_idea_cards(mission, artifacts, (), similarity_threshold=0.54)
    distinct = next(card for card in cards if "checksum receipt" in card.core_mechanism)
    assert distinct.minority_preserved


def test_problem_foundry_preserves_categories_without_write_authority(tmp_path: Path) -> None:
    service = _service(tmp_path)
    observations = {
        category: (
            {
                "observed_condition": f"{category} fixture",
                "why_it_matters": "This condition blocks measurable progress.",
                "evidence": (f"sha256:{category}",),
                "affected_parties": ("operators",),
                "current_approaches": ("retain the receipt",),
                "approach_failures": ("the condition remains unresolved",),
                "hidden_assumptions": ("the evidence source is complete",),
                "expected_leverage": 0.8,
                "tractability": 0.7,
                "novelty": "NOVELTY_UNVERIFIED",
                "proposed_measurement": "Measure the repaired gate.",
                "falsification_test": "The frozen condition persists.",
                "candidate_solution_families": ("proof_repair", "simpler_baseline"),
            },
        )
        for category in (
            "rejection",
            "quality_diversity_gap",
            "runtime_failure",
            "proof_debt",
            "bottleneck",
            "unresolved_decision",
        )
    }
    cards = collect_problem_portfolio(service.repository, observations, 6)
    assert {card.category for card in cards} == set(observations)
    tournament = problem_solution_tournament(
        cards,
        {
            "proof_repair": {"evidence": 0.8, "feasibility": 0.7, "risk": 0.2},
            "simpler_baseline": {"evidence": 0.6, "feasibility": 0.9, "risk": 0.1},
        },
    )
    assert tournament
    assert all(
        result["authority_effect"] == "PROPOSAL_ONLY_NO_CROSS_PROJECT_WRITE"
        for result in tournament
    )


@pytest.mark.skipif(not _sandbox_available(), reason="WSL2 Ubuntu bubblewrap is not available")
def test_real_attended_mission_reaches_measured_attribution(tmp_path: Path) -> None:
    service = _service(tmp_path)
    mission = service.create_mission(_mission_payload(), operator_approved=False)
    export_dir = tmp_path / "packet-export"
    exports = service.export_packets(mission.mission_id, export_dir)
    assert len(exports) == 6
    assert all(Path(item["prompt_path"]).is_file() for item in exports)

    _import_pending(service, mission.mission_id)
    service.advance_round(mission.mission_id)
    _import_pending(service, mission.mission_id)
    service.advance_round(mission.mission_id)
    _import_pending(service, mission.mission_id)
    service.advance_round(mission.mission_id)

    verified = service.verify_evidence(mission.mission_id)
    assert verified
    assert all(card.novelty_status.value == "POSSIBLY_NOVEL_MECHANISM" for card in verified)
    assert all(
        record.status.value == "UNVERIFIED"
        for card in verified
        for record in card.evidence_records
    )
    candidate = service.candidates(mission.mission_id)[0]
    source_a = "from __future__ import annotations\n\ndef solve(value):\n    return value\n"
    source_b = "def solve(value):\n    result = value\n    return result\n"
    experiment = service.run_experiment(
        mission_id=mission.mission_id,
        candidate_id=candidate.candidate_id,
        implementation_sources=(source_a, source_b),
        implementation_provider_ids=("chatgpt", "claude"),
        test_provider_id="deepseek",
        baseline_score=1000.0,
    )
    assert experiment.tests_passed
    assert experiment.differential_match
    assert experiment.network_disabled
    assert experiment.source_repo_untouched

    decision, attributions = service.decide_and_attribute(
        mission.mission_id,
        value_of_information=0.2,
        apply_learning=False,
    )
    assert decision.action is DecisionAction.ACT
    assert decision.authority_effect == "SUBMIT_TO_EXISTING_DOOFUS_GATES_ONLY"
    assert attributions
    assert service.current_stage(mission.mission_id) is MissionStage.ATTRIBUTED
    reports = service.generate_reports(mission.mission_id, tmp_path / "reports")
    assert all(Path(path).is_file() for path in reports.values())
    assert service.repository.verify_event_chain()["valid"]
