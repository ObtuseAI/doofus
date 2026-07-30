"""Cohesive application service for the attended Doofus Agora workflow."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from doofus.agora.capture import build_alias_map, import_response
from doofus.agora.code_lab import SandboxLimits, WslBubblewrapSandbox
from doofus.agora.config import (
    default_config_dir,
    default_runtime_root,
    load_provider_nodes,
    load_roles,
    load_security_policy,
    load_terms_sources,
    load_topologies,
)
from doofus.agora.contracts import (
    CandidateSpec,
    ContextClass,
    DecisionRecord,
    ExperimentResult,
    IdeaCard,
    MissionStage,
    OutcomeAttribution,
    PromptPacket,
    ProviderNode,
    ResponseArtifact,
    RoundType,
    SanitizationReceipt,
    SwarmMission,
    TermsDecision,
    TermsStatus,
)
from doofus.agora.debate import (
    build_critique_packets,
    build_idea_cards,
    build_synthesis_packets,
    stop_decision,
)
from doofus.agora.decision import (
    build_decision,
    build_decision_analysis,
    compile_candidate_spec,
)
from doofus.agora.errors import (
    EvidenceRetrievalError,
    MissionStateError,
    ResponseImportError,
)
from doofus.agora.evidence import EvidenceFabric, KeylessEvidenceFabric, verify_idea_card
from doofus.agora.learning import (
    apply_existing_learning_loops,
    build_attribution,
    quality_diversity_niche,
    record_provider_learning,
)
from doofus.agora.mission import (
    compile_divergence_packets,
    mission_from_mapping,
    transition_stage,
)
from doofus.agora.problem_foundry import collect_problem_portfolio
from doofus.agora.providers import (
    AssistedAdapter,
    AttendedAdapter,
    select_topology,
)
from doofus.agora.reports import configuration_hashes, write_reports
from doofus.agora.security import assert_export_allowed, sanitize_context
from doofus.agora.storage import AgoraRepository
from doofus.core.doofus_events import utc_now

ModelT = TypeVar("ModelT", bound=BaseModel)


class AgoraService:
    """Explicit orchestration boundary; imported provider content remains inert."""

    def __init__(
        self,
        repository: AgoraRepository,
        providers: tuple[ProviderNode, ...],
        roles: dict[str, dict[str, Any]],
        topologies: dict[str, dict[str, Any]],
        security_policy: dict[str, Any],
        terms_sources: dict[str, str],
        evidence_fabric: EvidenceFabric,
        config_dir: Path,
        runtime_root: Path,
    ) -> None:
        self._repository = repository
        self._providers = providers
        self._roles = roles
        self._topologies = topologies
        self._security_policy = security_policy
        self._terms_sources = terms_sources
        self._evidence_fabric = evidence_fabric
        self._config_dir = config_dir
        self._runtime_root = runtime_root

    @classmethod
    def create_default(
        cls,
        config_dir: Path | None = None,
        runtime_root: Path | None = None,
    ) -> AgoraService:
        selected_config = config_dir or default_config_dir()
        selected_runtime = runtime_root or default_runtime_root()
        repository = AgoraRepository(
            database_path=selected_runtime / "agora.sqlite",
            vault_root=selected_runtime / "vault",
        )
        repository.initialize()
        policy = load_security_policy(selected_config)
        evidence_policy = dict(policy["evidence_retrieval"])
        fabric = KeylessEvidenceFabric(
            repository=repository,
            timeout_seconds=float(evidence_policy["timeout_seconds"]),
            maximum_bytes=int(evidence_policy["maximum_bytes"]),
            retry_count=int(evidence_policy["retry_count"]),
            maximum_redirects=int(evidence_policy["maximum_redirects"]),
            allowed_content_types=tuple(
                str(item) for item in evidence_policy["allowed_content_types"]
            ),
        )
        return cls(
            repository=repository,
            providers=load_provider_nodes(selected_config),
            roles=load_roles(selected_config),
            topologies=load_topologies(selected_config),
            security_policy=policy,
            terms_sources=load_terms_sources(selected_config),
            evidence_fabric=fabric,
            config_dir=selected_config,
            runtime_root=selected_runtime,
        )

    @property
    def repository(self) -> AgoraRepository:
        return self._repository

    @property
    def providers(self) -> tuple[ProviderNode, ...]:
        return self._providers

    def create_mission(
        self,
        payload: dict[str, Any],
        operator_approved: bool,
    ) -> SwarmMission:
        raw_context_class = payload.get("context_class")
        if raw_context_class is None or not str(raw_context_class).strip():
            raw_context_class = ContextClass.SECRET.value
        context_class = ContextClass(str(raw_context_class))
        sanitized, receipt = sanitize_context(
            text=str(payload.get("context", "")),
            context_class=context_class,
            operator_approved=operator_approved,
        )
        assert_export_allowed(receipt)
        selected_payload = dict(payload)
        if str(selected_payload.get("topology_id")) == "AUTO":
            selection_seed = int.from_bytes(
                hashlib.sha256(
                    (
                        f"{selected_payload.get('mission_type', '')}:"
                        f"{selected_payload.get('objective', '')}"
                    ).encode("utf-8")
                ).digest()[:8],
                "big",
            )
            selected_payload["topology_id"] = select_topology(
                tuple(self._topologies),
                str(selected_payload["mission_type"]),
                selection_seed,
                self._repository,
            )
        mission = mission_from_mapping(
            {**selected_payload, "context_class": context_class.value},
            sanitized,
        )
        if mission.topology_id not in self._topologies:
            raise MissionStateError(f"unknown Agora topology: {mission.topology_id}")
        self._repository.append_event(
            mission.mission_id,
            "mission_created",
            {"mission": mission.model_dump(mode="json")},
        )
        self._repository.append_event(
            mission.mission_id,
            "sanitization_receipt",
            {"receipt": receipt.model_dump(mode="json")},
        )
        self._record_stage(mission.mission_id, MissionStage.DRAFT, MissionStage.SANITIZED)
        packets = compile_divergence_packets(
            mission=mission,
            providers=self._providers,
            roles=self._roles,
            topology=self._topologies[mission.topology_id],
            repository=self._repository,
        )
        for packet in packets:
            self._record_packet(packet)
        self._record_stage(
            mission.mission_id,
            MissionStage.SANITIZED,
            MissionStage.PACKETS_READY,
        )
        return mission

    def mission(self, mission_id: str) -> SwarmMission:
        event = self._first_event(mission_id, "mission_created")
        return SwarmMission.model_validate(event["payload"]["mission"])

    def current_stage(self, mission_id: str) -> MissionStage:
        self.mission(mission_id)
        stages = [
            MissionStage(str(event["payload"]["stage"]))
            for event in self._repository.mission_events(mission_id)
            if event["event_type"] == "mission_stage"
        ]
        return stages[-1] if stages else MissionStage.DRAFT

    def packets(self, mission_id: str) -> tuple[PromptPacket, ...]:
        return self._event_models(mission_id, "packet_created", "packet", PromptPacket)

    def responses(self, mission_id: str) -> tuple[ResponseArtifact, ...]:
        return self._event_models(mission_id, "response_imported", "response", ResponseArtifact)

    def idea_cards(self, mission_id: str) -> tuple[IdeaCard, ...]:
        events = self._repository.mission_events(mission_id)
        by_id: dict[str, IdeaCard] = {}
        for event in events:
            if event["event_type"] in {"idea_formalized", "idea_verified"}:
                card = IdeaCard.model_validate(event["payload"]["idea"])
                by_id[card.idea_id] = card
        return tuple(by_id.values())

    def candidates(self, mission_id: str) -> tuple[CandidateSpec, ...]:
        return self._event_models(mission_id, "candidate_formalized", "candidate", CandidateSpec)

    def experiments(self, mission_id: str) -> tuple[ExperimentResult, ...]:
        return self._event_models(mission_id, "experiment_recorded", "experiment", ExperimentResult)

    def export_packets(self, mission_id: str, destination: Path) -> tuple[dict[str, str], ...]:
        receipt = SanitizationReceipt.model_validate(
            self._first_event(mission_id, "sanitization_receipt")["payload"]["receipt"]
        )
        assert_export_allowed(receipt)
        provider_by_id = {provider.provider_id: provider for provider in self._providers}
        exports: list[dict[str, str]] = []
        imported_packet_ids = {response.packet_id for response in self.responses(mission_id)}
        for packet in self.packets(mission_id):
            if packet.packet_id in imported_packet_ids:
                continue
            provider = provider_by_id[packet.provider_id]
            adapter = (
                AssistedAdapter()
                if provider.execution_mode.value == "ASSISTED"
                else AttendedAdapter()
            )
            prompt_path, manifest_path = adapter.export_packet(packet, destination)
            exports.append(
                {
                    "packet_id": packet.packet_id,
                    "provider_id": packet.provider_id,
                    "prompt_path": str(prompt_path),
                    "manifest_path": str(manifest_path),
                }
            )
        if self.current_stage(mission_id) is MissionStage.PACKETS_READY:
            self._record_stage(
                mission_id,
                MissionStage.PACKETS_READY,
                MissionStage.COLLECTING,
            )
        self._repository.append_event(
            mission_id,
            "packets_exported",
            {"exports": exports, "automation": "DISABLED_ATTENDED_LOCAL_FILES_ONLY"},
        )
        return tuple(exports)

    def import_response_text(self, packet_id: str, response_text: str) -> ResponseArtifact:
        packet = self._packet(packet_id)
        if any(response.packet_id == packet_id for response in self.responses(packet.mission_id)):
            raise ResponseImportError(f"response has already been imported for packet: {packet_id}")
        stage = self.current_stage(packet.mission_id)
        if stage is MissionStage.PACKETS_READY:
            self._record_stage(
                packet.mission_id,
                MissionStage.PACKETS_READY,
                MissionStage.COLLECTING,
            )
        elif stage not in {MissionStage.COLLECTING, MissionStage.DEBATING}:
            raise MissionStateError(
                f"responses cannot be imported while mission is {stage.value}"
            )
        artifact = import_response(packet, response_text, self._repository)
        self._repository.append_event(
            packet.mission_id,
            "response_imported",
            {"response": artifact.model_dump(mode="json")},
        )
        return artifact

    def advance_round(self, mission_id: str) -> dict[str, Any]:
        mission = self.mission(mission_id)
        packets = self.packets(mission_id)
        responses = self.responses(mission_id)
        response_packet_ids = {response.packet_id for response in responses}
        pending = tuple(packet.packet_id for packet in packets if packet.packet_id not in response_packet_ids)
        if pending:
            raise MissionStateError(
                f"round cannot advance with pending attended responses: {pending}"
            )
        divergence = tuple(
            response for response in responses if response.round_type is RoundType.DIVERGENCE
        )
        critiques = tuple(
            response for response in responses if response.round_type is RoundType.CRITIQUE
        )
        synthesis = tuple(
            response for response in responses if response.round_type is RoundType.SYNTHESIS
        )
        has_critique_packets = any(packet.round_type is RoundType.CRITIQUE for packet in packets)
        has_synthesis_packets = any(packet.round_type is RoundType.SYNTHESIS for packet in packets)
        if not has_critique_packets:
            self._repository.append_event(
                mission_id,
                "stop_controller_evaluated",
                stop_decision(
                    current_round=1,
                    maximum_rounds=mission.maximum_rounds,
                    new_mechanisms=len(divergence),
                    contradiction_reduction=1.0,
                    decisive_experiment_available=False,
                    quota_exhausted=False,
                    expected_value_next_round=1.0,
                ),
            )
            aliases = build_alias_map(mission.mission_id, mission.routing_seed, divergence)
            self._repository.append_event(
                mission_id,
                "alias_map_created",
                {"protected_mapping": aliases},
            )
            pairs = build_critique_packets(mission, divergence, aliases)
            for packet, card in pairs:
                self._record_packet(packet)
                self._repository.append_event(
                    mission_id,
                    "critique_assigned",
                    {"critique": card.model_dump(mode="json")},
                )
            self._record_stage(
                mission_id,
                MissionStage.COLLECTING,
                MissionStage.DEBATING,
            )
            return {"advanced_to": RoundType.CRITIQUE.value, "packet_count": len(pairs)}
        if not has_synthesis_packets:
            self._repository.append_event(
                mission_id,
                "stop_controller_evaluated",
                stop_decision(
                    current_round=2,
                    maximum_rounds=mission.maximum_rounds,
                    new_mechanisms=len(critiques),
                    contradiction_reduction=0.5,
                    decisive_experiment_available=False,
                    quota_exhausted=False,
                    expected_value_next_round=0.5,
                ),
            )
            aliases = self._alias_map(mission_id)
            new_packets = build_synthesis_packets(mission, divergence, critiques, aliases)
            for packet in new_packets:
                self._record_packet(packet)
            return {"advanced_to": RoundType.SYNTHESIS.value, "packet_count": len(new_packets)}
        cards = build_idea_cards(
            mission,
            divergence,
            synthesis,
            float(self._security_policy["debate"]["similarity_threshold"]),
        )
        for card in cards:
            niche = quality_diversity_niche(card)
            archive_receipt = self._repository.upsert_quality_archive(
                niche,
                card,
                card.confidence,
            )
            self._repository.append_event(
                mission_id,
                "idea_formalized",
                {
                    "idea": card.model_dump(mode="json"),
                    "quality_diversity_niche": niche,
                    "quality_archive_receipt": archive_receipt,
                },
            )
        self._repository.append_event(
            mission_id,
            "stop_controller_evaluated",
            stop_decision(
                current_round=3,
                maximum_rounds=mission.maximum_rounds,
                new_mechanisms=len(cards),
                contradiction_reduction=0.25,
                decisive_experiment_available=True,
                quota_exhausted=False,
                expected_value_next_round=0.0,
            ),
        )
        self._record_stage(
            mission_id,
            MissionStage.DEBATING,
            MissionStage.VERIFYING,
        )
        return {
            "advanced_to": MissionStage.VERIFYING.value,
            "idea_count": len(cards),
            "minority_count": sum(card.minority_preserved for card in cards),
        }

    def verify_evidence(self, mission_id: str) -> tuple[IdeaCard, ...]:
        if self.current_stage(mission_id) is not MissionStage.VERIFYING:
            raise MissionStateError("evidence verification requires mission stage VERIFYING")
        verified: list[IdeaCard] = []
        for card in self.idea_cards(mission_id):
            checked = verify_idea_card(card, self._evidence_fabric)
            self._repository.append_event(
                mission_id,
                "idea_verified",
                {"idea": checked.model_dump(mode="json")},
            )
            verified.append(checked)
        self._record_stage(
            mission_id,
            MissionStage.VERIFYING,
            MissionStage.FORMALIZED,
        )
        all_artifact_ids = tuple(
            response.artifact_id for response in self.responses(mission_id)
        )
        mission = self.mission(mission_id)
        for card in verified:
            candidate = compile_candidate_spec(
                card,
                mission.candidate_test_cases,
                mission.benchmark_baseline_score,
                all_artifact_ids,
            )
            self._repository.append_event(
                mission_id,
                "candidate_formalized",
                {"candidate": candidate.model_dump(mode="json")},
            )
        self._record_stage(
            mission_id,
            MissionStage.FORMALIZED,
            MissionStage.EXPERIMENT_READY,
        )
        return tuple(verified)

    def run_experiment(
        self,
        mission_id: str,
        candidate_id: str,
        implementation_sources: tuple[str, str],
        implementation_provider_ids: tuple[str, str],
        test_provider_id: str,
        baseline_score: float,
    ) -> ExperimentResult:
        if self.current_stage(mission_id) is not MissionStage.EXPERIMENT_READY:
            raise MissionStateError("sandbox execution requires mission stage EXPERIMENT_READY")
        candidate = next(
            (
                item
                for item in self.candidates(mission_id)
                if item.candidate_id == candidate_id
            ),
            None,
        )
        if candidate is None:
            raise MissionStateError(f"unknown candidate for mission {mission_id}: {candidate_id}")
        if abs(baseline_score - candidate.benchmark_baseline_score) > 1e-12:
            raise MissionStateError(
                "experiment baseline does not match the frozen CandidateSpec: "
                f"candidate={candidate.benchmark_baseline_score} supplied={baseline_score}"
            )
        sandbox_policy = dict(self._security_policy["sandbox"])
        sandbox = WslBubblewrapSandbox(
            repository=self._repository,
            sandbox_root=self._runtime_root / "sandboxes",
            distribution=str(sandbox_policy["wsl_distribution"]),
            limits=SandboxLimits(
                timeout_seconds=float(sandbox_policy["timeout_seconds"]),
                cpu_seconds=int(sandbox_policy["cpu_seconds"]),
                memory_bytes=int(sandbox_policy["memory_bytes"]),
                process_count=int(sandbox_policy["process_count"]),
                output_bytes=int(sandbox_policy["output_bytes"]),
            ),
        )
        result = sandbox.run_candidate(
            candidate=candidate,
            implementation_sources=implementation_sources,
            implementation_provider_ids=implementation_provider_ids,
            test_provider_id=test_provider_id,
            baseline_score=baseline_score,
        )
        self._repository.append_event(
            mission_id,
            "experiment_recorded",
            {"experiment": result.model_dump(mode="json")},
        )
        card_by_idea = {
            card.idea_id: card for card in self.idea_cards(mission_id)
        }
        measured_card = card_by_idea[candidate.idea_id]
        measured_score = (
            1.0
            if result.tests_passed and result.differential_match
            else 0.0
        )
        self._repository.upsert_quality_archive(
            quality_diversity_niche(measured_card),
            measured_card,
            measured_score,
        )
        self._record_stage(
            mission_id,
            MissionStage.EXPERIMENT_READY,
            MissionStage.EXPERIMENTED,
        )
        return result

    def decide_and_attribute(
        self,
        mission_id: str,
        value_of_information: float,
        apply_learning: bool,
    ) -> tuple[DecisionRecord, tuple[OutcomeAttribution, ...]]:
        if self.current_stage(mission_id) is not MissionStage.EXPERIMENTED:
            raise MissionStateError("final decision requires mission stage EXPERIMENTED")
        mission = self.mission(mission_id)
        cards = self.idea_cards(mission_id)
        candidates = self.candidates(mission_id)
        experiments = self.experiments(mission_id)
        decision = build_decision(
            mission_id,
            cards,
            candidates,
            experiments,
            value_of_information,
        )
        self._repository.append_event(
            mission_id,
            "decision_analysis_recorded",
            {"analysis": build_decision_analysis(cards)},
        )
        self._repository.append_event(
            mission_id,
            "decision_recorded",
            {"decision": decision.model_dump(mode="json")},
        )
        self._record_stage(
            mission_id,
            MissionStage.EXPERIMENTED,
            MissionStage.DECIDED,
        )
        card_by_idea = {card.idea_id: card for card in cards}
        candidate_by_id = {candidate.candidate_id: candidate for candidate in candidates}
        artifacts = self.responses(mission_id)
        attributions: list[OutcomeAttribution] = []
        for experiment in experiments:
            candidate = candidate_by_id[experiment.candidate_id]
            card = card_by_idea[candidate.idea_id]
            attribution = build_attribution(
                mission,
                decision,
                card,
                experiment,
                artifacts,
            )
            self._repository.append_event(
                mission_id,
                "outcome_attributed",
                {"attribution": attribution.model_dump(mode="json")},
            )
            record_provider_learning(
                mission,
                attribution,
                card,
                artifacts,
                self._repository,
            )
            self._repository.append_event(
                mission_id,
                "arena_candidate_handoff",
                {
                    "candidate_id": experiment.candidate_id,
                    "experiment_id": experiment.experiment_id,
                    "status": "ELIGIBLE_FOR_EXISTING_ARENAS"
                    if decision.action.value == "ACT"
                    else "BLOCKED",
                    "authority_effect": "HANDOFF_ONLY_NO_PROMOTION_OR_SOURCE_MUTATION",
                },
            )
            if apply_learning:
                source_prompt = self._packet(artifacts[0].packet_id).prompt_text if artifacts else ""
                learning_receipt = apply_existing_learning_loops(
                    attribution,
                    decision,
                    card,
                    source_prompt,
                )
                self._repository.append_event(
                    mission_id,
                    "existing_learning_loops_updated",
                    {"candidate_id": experiment.candidate_id, "receipt": learning_receipt},
                )
            attributions.append(attribution)
        self._record_stage(
            mission_id,
            MissionStage.DECIDED,
            MissionStage.ATTRIBUTED,
        )
        return decision, tuple(attributions)

    def build_problem_portfolio(
        self,
        mission_id: str,
        observations_by_category: dict[str, tuple[dict[str, Any], ...]],
        maximum_cards: int,
    ) -> tuple[dict[str, Any], ...]:
        self.mission(mission_id)
        cards = collect_problem_portfolio(
            self._repository,
            observations_by_category,
            maximum_cards,
        )
        for card in cards:
            self._repository.append_event(
                mission_id,
                "problem_card_collected",
                {"problem": card.model_dump(mode="json")},
            )
        return tuple(card.model_dump(mode="json") for card in cards)

    def refresh_terms(self, provider_id: str) -> TermsDecision:
        source_url = self._terms_source(provider_id)
        try:
            source = self._evidence_fabric.fetch_url(source_url)
            latest = self._repository.latest_terms_decision(provider_id)
            status = (
                TermsStatus.REVIEW_REQUIRED
                if latest is None or latest.document_sha256 != source.sha256
                else latest.status
            )
            decision = TermsDecision(
                provider_id=provider_id,
                source_url=source.url,
                document_sha256=source.sha256,
                reviewed_at=utc_now(),
                reviewer="SYSTEM_REFRESH_REQUIRES_OPERATOR_REVIEW",
                status=status,
                automated_submit_allowed=False,
                automated_extract_allowed=False,
                notes="Terms source fetched and frozen; changed content requires a new operator decision.",
            )
        except EvidenceRetrievalError as exc:
            error_payload = str(exc).encode("utf-8")
            digest, _ = self._repository.store_blob("terms_refresh_failure", error_payload)
            decision = TermsDecision(
                provider_id=provider_id,
                source_url=source_url,
                document_sha256=digest,
                reviewed_at=utc_now(),
                reviewer="SYSTEM_REFRESH",
                status=TermsStatus.BLOCKED,
                automated_submit_allowed=False,
                automated_extract_allowed=False,
                notes=f"Terms source unavailable; automation blocked: {exc}",
            )
        self._repository.record_terms_decision(decision)
        self._repository.append_event(
            "TERMS",
            "terms_decision_recorded",
            {"decision": decision.model_dump(mode="json")},
        )
        return decision

    def review_terms(
        self,
        provider_id: str,
        reviewer: str,
        status: TermsStatus,
        automated_submit_allowed: bool,
        automated_extract_allowed: bool,
        notes: str,
    ) -> TermsDecision:
        refreshed = self.refresh_terms(provider_id)
        if refreshed.status is TermsStatus.BLOCKED:
            return refreshed
        decision = TermsDecision(
            provider_id=provider_id,
            source_url=refreshed.source_url,
            document_sha256=refreshed.document_sha256,
            reviewed_at=utc_now(),
            reviewer=reviewer,
            status=status,
            automated_submit_allowed=automated_submit_allowed,
            automated_extract_allowed=automated_extract_allowed,
            notes=notes,
        )
        self._repository.record_terms_decision(decision)
        self._repository.append_event(
            "TERMS",
            "terms_decision_recorded",
            {"decision": decision.model_dump(mode="json")},
        )
        return decision

    def generate_reports(self, mission_id: str, destination: Path) -> dict[str, str]:
        return write_reports(
            mission_id,
            destination,
            self._repository,
            configuration_hashes(self._config_dir),
        )

    def snapshot(self, event_limit: int) -> dict[str, Any]:
        events = self._repository.all_events(event_limit)
        mission_ids = tuple(
            dict.fromkeys(event["mission_id"] for event in events if event["mission_id"] != "TERMS")
        )
        return {
            "classification": "AGORA_ATTENDED_OPERATIONAL",
            "authority_ceiling": "CANDIDATE_HANDOFF_ONLY",
            "consumer_browser_automation": "DISABLED",
            "providers": [
                {
                    **provider.model_dump(mode="json"),
                    "latest_terms_decision": (
                        decision.model_dump(mode="json")
                        if (decision := self._repository.latest_terms_decision(provider.provider_id))
                        else None
                    ),
                }
                for provider in self._providers
            ],
            "missions": [
                {
                    "mission_id": mission_id,
                    "objective": self.mission(mission_id).objective,
                    "stage": self.current_stage(mission_id).value,
                    "event_count": len(self._repository.mission_events(mission_id)),
                }
                for mission_id in mission_ids
            ],
            "event_chain": self._repository.verify_event_chain(),
            "quality_archive": self._repository.quality_archive_snapshot(12),
        }

    def _record_packet(self, packet: PromptPacket) -> None:
        prompt_digest, _ = self._repository.store_blob(
            "prompt_packet",
            packet.prompt_text.encode("utf-8"),
        )
        if prompt_digest != packet.prompt_sha256:
            raise MissionStateError(
                f"compiled packet hash does not match vault hash: packet={packet.packet_id}"
            )
        self._repository.append_event(
            packet.mission_id,
            "packet_created",
            {"packet": packet.model_dump(mode="json")},
        )

    def _record_stage(
        self,
        mission_id: str,
        current: MissionStage,
        next_stage: MissionStage,
    ) -> None:
        actual = self.current_stage(mission_id)
        if actual is not current:
            raise MissionStateError(
                f"mission stage changed unexpectedly: expected={current.value} actual={actual.value}"
            )
        transition_stage(current, next_stage)
        self._repository.append_event(
            mission_id,
            "mission_stage",
            {"stage": next_stage.value},
        )

    def _first_event(self, mission_id: str, event_type: str) -> dict[str, Any]:
        event = next(
            (
                item
                for item in self._repository.mission_events(mission_id)
                if item["event_type"] == event_type
            ),
            None,
        )
        if event is None:
            raise MissionStateError(
                f"mission event is missing: mission={mission_id} event_type={event_type}"
            )
        return event

    def _event_models(
        self,
        mission_id: str,
        event_type: str,
        payload_key: str,
        model_type: type[ModelT],
    ) -> tuple[ModelT, ...]:
        return tuple(
            model_type.model_validate(event["payload"][payload_key])
            for event in self._repository.mission_events(mission_id)
            if event["event_type"] == event_type
        )

    def _packet(self, packet_id: str) -> PromptPacket:
        events = self._repository.all_events(100000)
        for event in events:
            if event["event_type"] != "packet_created":
                continue
            packet = PromptPacket.model_validate(event["payload"]["packet"])
            if packet.packet_id == packet_id:
                return packet
        raise ResponseImportError(f"unknown attended packet: {packet_id}")

    def _alias_map(self, mission_id: str) -> dict[str, str]:
        event = self._first_event(mission_id, "alias_map_created")
        return {
            str(key): str(value)
            for key, value in dict(event["payload"]["protected_mapping"]).items()
        }

    def _terms_source(self, provider_id: str) -> str:
        if provider_id not in self._terms_sources:
            raise MissionStateError(f"provider has no tracked terms source: {provider_id}")
        return self._terms_sources[provider_id]


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
