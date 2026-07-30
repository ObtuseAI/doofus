"""Scoped NiceGUI operator console for attended Doofus Agora missions."""

from __future__ import annotations

from typing import Any

from nicegui import ui

from doofus.agora.contracts import ContextClass
from doofus.agora.errors import AgoraError
from doofus.agora.security import sanitize_context
from doofus.agora.service import AgoraService

AGORA_CSS = """
.agora-shell {
    --agora-bg: #0b1020;
    --agora-surface: #111a2e;
    --agora-surface-raised: #17233c;
    --agora-border: #30415f;
    --agora-text: #f2f6ff;
    --agora-muted: #a7b4c9;
    --agora-primary: #78a9ff;
    --agora-accent: #f5b942;
    --agora-success: #5fd5a0;
    --agora-danger: #ff8b92;
    color: var(--agora-text);
    background:
        radial-gradient(circle at 82% 4%, rgba(74, 118, 211, 0.18), transparent 34rem),
        var(--agora-bg);
    border: 1px solid var(--agora-border);
    border-radius: 16px;
    padding: 24px;
    min-height: 70vh;
}
.agora-grid {
    display: grid;
    grid-template-columns: repeat(12, minmax(0, 1fr));
    gap: 16px;
    width: 100%;
}
.agora-span-4 { grid-column: span 4; }
.agora-span-5 { grid-column: span 5; }
.agora-span-7 { grid-column: span 7; }
.agora-span-8 { grid-column: span 8; }
.agora-span-12 { grid-column: span 12; }
.agora-card {
    background: var(--agora-surface) !important;
    border: 1px solid var(--agora-border) !important;
    border-radius: 12px !important;
    box-shadow: 0 10px 28px rgba(0, 0, 0, 0.22) !important;
    padding: 20px !important;
    min-width: 0;
}
.agora-kicker {
    color: var(--agora-primary);
    font: 700 12px/1.4 "Fira Code", Consolas, monospace;
    letter-spacing: 0.12em;
    text-transform: uppercase;
}
.agora-title {
    color: var(--agora-text);
    font: 700 clamp(24px, 3vw, 40px)/1.08 "Fira Sans", system-ui, sans-serif;
    max-width: 22ch;
}
.agora-body, .agora-shell .q-field__native, .agora-shell .q-field__label {
    color: var(--agora-text) !important;
}
.agora-muted { color: var(--agora-muted); line-height: 1.6; }
.agora-metric {
    color: var(--agora-text);
    font: 700 24px/1.1 "Fira Code", Consolas, monospace;
}
.agora-status {
    border: 1px solid var(--agora-border);
    border-radius: 999px;
    color: var(--agora-success);
    font: 700 11px/1 "Fira Code", Consolas, monospace;
    padding: 8px 12px;
}
.agora-flow {
    display: grid;
    grid-template-columns: repeat(5, minmax(0, 1fr));
    gap: 8px;
    align-items: stretch;
}
.agora-flow-step {
    border-left: 3px solid var(--agora-primary);
    background: var(--agora-surface-raised);
    padding: 12px;
    min-height: 72px;
}
.agora-flow-step strong { display: block; color: var(--agora-text); }
.agora-flow-step span { color: var(--agora-muted); font-size: 12px; }
.agora-shell .q-btn {
    min-height: 44px;
    transition: background-color 180ms ease, border-color 180ms ease, opacity 180ms ease;
}
.agora-shell .q-btn:focus-visible,
.agora-shell .q-field--focused,
.agora-shell [tabindex]:focus-visible {
    outline: 3px solid var(--agora-accent) !important;
    outline-offset: 3px;
    box-shadow: 0 0 0 3px var(--agora-accent) !important;
}
.agora-shell button:focus-visible,
.agora-shell input:focus-visible,
.agora-shell textarea:focus-visible,
.agora-shell [role="combobox"]:focus-visible {
    outline: 3px solid var(--agora-accent) !important;
    outline-offset: 3px;
    box-shadow: 0 0 0 3px var(--agora-accent) !important;
}
.agora-shell .q-table__container {
    background: transparent;
    color: var(--agora-text);
    overflow-x: auto;
}
.agora-shell .q-table thead tr,
.agora-shell .q-table tbody td {
    color: var(--agora-text);
    border-color: var(--agora-border);
}
.agora-shell .q-field {
    min-height: 48px;
}
@media (max-width: 1023px) {
    .agora-span-4, .agora-span-5, .agora-span-7, .agora-span-8 { grid-column: span 6; }
    .agora-flow { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
@media (max-width: 767px) {
    .agora-shell { padding: 16px; border-radius: 12px; }
    .agora-span-4, .agora-span-5, .agora-span-7, .agora-span-8, .agora-span-12 {
        grid-column: span 12;
    }
    .agora-flow { grid-template-columns: 1fr; }
    .agora-title { font-size: 28px; }
}
@media (prefers-reduced-motion: reduce) {
    .agora-shell *, .agora-shell *::before, .agora-shell *::after {
        animation-duration: 0.01ms !important;
        animation-iteration-count: 1 !important;
        scroll-behavior: auto !important;
        transition-duration: 0.01ms !important;
    }
}
"""


def _event_rows(service: AgoraService, mission_id: str, event_type: str, payload_key: str) -> list[dict[str, Any]]:
    return [
        dict(event["payload"][payload_key])
        for event in service.repository.mission_events(mission_id)
        if event["event_type"] == event_type
    ]


def _latest_mission_id(snapshot: dict[str, Any]) -> str | None:
    missions = list(snapshot.get("missions", []))
    return str(missions[0]["mission_id"]) if missions else None


def _section(label: str, title: str, description: str) -> None:
    ui.label(label).classes("agora-kicker")
    ui.label(title).classes("text-h6 agora-body")
    ui.label(description).classes("text-body2 agora-muted")


def _build_mission_composer(service: AgoraService) -> None:
    _section(
        "Mission compiler",
        "Launch a bounded inquiry",
        "Context classification is mandatory. SECRET never leaves the local trust boundary.",
    )
    objective = ui.textarea(
        label="Objective",
        placeholder="What mechanism should the swarm invent or falsify?",
    ).classes("w-full")
    decision = ui.input(
        label="Decision to inform",
        placeholder="What operator decision will this evidence inform?",
    ).classes("w-full")
    target = ui.input(
        label="Target project",
        value="doofus",
    ).classes("w-full")
    context = ui.textarea(
        label="Context",
        placeholder="Only public or explicitly sanitized context may be exported.",
    ).classes("w-full")
    with ui.row().classes("w-full gap-3"):
        context_class = ui.select(
            options=[item.value for item in ContextClass],
            label="Context class",
            value=None,
        ).classes("grow")
        topology = ui.select(
            options=[
                "frontier_hexagon",
                "red_blue_foundry",
                "evidence_funnel",
                "problem_solution_coevolution",
            ],
            label="Debate topology",
            value="frontier_hexagon",
        ).classes("grow")
    operator_approved = ui.checkbox(
        "I reviewed the sanitation receipt for SANITIZED_INTERNAL context"
    )
    preview = ui.label("Sanitation preview has not run.").classes("text-caption agora-muted")

    def preview_context() -> None:
        try:
            selected = ContextClass(str(context_class.value or ContextClass.SECRET.value))
            sanitized, receipt = sanitize_context(
                str(context.value or ""),
                selected,
                bool(operator_approved.value),
            )
            preview.set_text(
                f"{len(receipt.findings)} sensitive finding(s); "
                f"sanitized SHA-256 {receipt.sanitized_sha256[:16]}…; "
                f"preview: {sanitized[:180]}"
            )
        except (AgoraError, ValueError) as exc:
            preview.set_text(f"Blocked: {exc}")

    def create_mission() -> None:
        try:
            mission = service.create_mission(
                {
                    "mission_type": "invention",
                    "objective": str(objective.value or ""),
                    "decision_to_inform": str(decision.value or ""),
                    "target_project": str(target.value or ""),
                    "context": str(context.value or ""),
                    "context_class": context_class.value,
                    "known_evidence": [],
                    "hard_constraints": [
                        "Preserve every existing Doofus promotion and safety gate.",
                        "ACT only creates a candidate handoff.",
                    ],
                    "forbidden_actions": [
                        "Browser submission, scraping, or provider-content extraction.",
                        "Primary-repository mutation or cross-project writes.",
                    ],
                    "success_metrics": ["A reproducible improvement over the declared baseline."],
                    "falsification_conditions": ["Independent implementations disagree or fail the contract."],
                    "open_questions": ["What is the cheapest decisive experiment?"],
                    "candidate_test_cases": [],
                    "benchmark_baseline_score": 0.0,
                    "maximum_nodes": 6,
                    "maximum_rounds": 3,
                    "topology_id": str(topology.value),
                },
                operator_approved=bool(operator_approved.value),
            )
            ui.notify(
                f"Mission {mission.mission_id} compiled into attended packets.",
                type="positive",
            )
        except (AgoraError, ValueError) as exc:
            ui.notify(f"Mission blocked: {exc}", type="negative", close_button=True)

    with ui.row().classes("w-full gap-3"):
        ui.button("Preview sanitation", on_click=preview_context).props("outline")
        ui.button("Create attended mission", on_click=create_mission).props("color=primary")


def _build_provider_matrix(snapshot: dict[str, Any]) -> None:
    _section(
        "Provider constitution",
        "Terms and execution are separate",
        "Every consumer node begins attended. Assisted means local clipboard/file staging only.",
    )
    rows = [
        {
            "provider": provider["display_name"],
            "core": "CORE" if provider["core_enabled"] else "RESERVE",
            "mode": provider["execution_mode"],
            "terms": (
                provider["latest_terms_decision"]["status"]
                if provider["latest_terms_decision"]
                else provider["terms_status"]
            ),
            "quota": provider["quota_state"],
        }
        for provider in snapshot.get("providers", [])
    ]
    ui.table(
        columns=[
            {"name": "provider", "label": "Provider", "field": "provider", "sortable": True},
            {"name": "core", "label": "Lane", "field": "core", "sortable": True},
            {"name": "mode", "label": "Execution", "field": "mode", "sortable": True},
            {"name": "terms", "label": "Terms", "field": "terms", "sortable": True},
            {"name": "quota", "label": "Quota", "field": "quota", "sortable": True},
        ],
        rows=rows,
        row_key="provider",
        pagination={"rowsPerPage": 10},
    ).classes("w-full")


def _build_flow(service: AgoraService, mission_id: str | None) -> None:
    _section(
        "Debate topology",
        "Diverge before evidence convergence",
        "Blind critique and mechanistic minority preservation replace majority voting.",
    )
    if mission_id is None:
        ui.label("No mission yet. Create one to populate the debate graph.").classes("agora-muted")
        return
    packets = service.packets(mission_id)
    responses = service.responses(mission_id)
    cards = service.idea_cards(mission_id)
    experiments = service.experiments(mission_id)
    stages = [
        ("Divergence", sum(packet.round_type.value == "DIVERGENCE" for packet in packets)),
        ("Blind critique", sum(packet.round_type.value == "CRITIQUE" for packet in packets)),
        ("Synthesis", sum(packet.round_type.value == "SYNTHESIS" for packet in packets)),
        ("Evidence", len(cards)),
        ("Experiment", len(experiments)),
    ]
    with ui.element("div").classes("agora-flow w-full"):
        for label, count in stages:
            with ui.element("div").classes("agora-flow-step"):
                ui.label(label).classes("text-weight-bold")
                ui.label(f"{count} artifact(s)").classes("text-caption")
    ui.label(
        f"{len(responses)} inert response artifact(s) captured; provider identities stay out of judge prompts."
    ).classes("text-caption agora-muted q-mt-sm")
    ui.label("Packet inbox").classes("agora-kicker q-mt-md")
    response_packet_ids = {response.packet_id for response in responses}
    packet_rows = [
        {
            "packet": packet.packet_id,
            "provider": packet.provider_id,
            "role": packet.role_id,
            "round": packet.round_type.value,
            "status": "IMPORTED" if packet.packet_id in response_packet_ids else "AWAITING_ATTENDED_IMPORT",
        }
        for packet in packets
    ]
    ui.table(
        columns=[
            {"name": "packet", "label": "Packet", "field": "packet"},
            {"name": "provider", "label": "Provider", "field": "provider", "sortable": True},
            {"name": "role", "label": "Role", "field": "role", "sortable": True},
            {"name": "round", "label": "Round", "field": "round", "sortable": True},
            {"name": "status", "label": "Status", "field": "status", "sortable": True},
        ],
        rows=packet_rows,
        row_key="packet",
        pagination={"rowsPerPage": 6},
    ).classes("w-full")


def _build_mission_evidence(service: AgoraService, mission_id: str | None) -> None:
    _section(
        "Evidence matrix",
        "Claims do not inherit source credibility",
        "Support requires an attributable excerpt, independent assessment, or measured result.",
    )
    rows: list[dict[str, Any]] = []
    if mission_id:
        for card in service.idea_cards(mission_id):
            for record in card.evidence_records:
                rows.append(
                    {
                        "claim": record.claim[:100],
                        "status": record.status.value,
                        "source": record.source_kind,
                        "detail": record.detail[:120],
                    }
                )
    if not rows:
        ui.label("No verified claims yet. Unavailable evidence will remain visibly blocked.").classes(
            "agora-muted"
        )
        return
    ui.table(
        columns=[
            {"name": "claim", "label": "Claim", "field": "claim"},
            {"name": "status", "label": "Status", "field": "status", "sortable": True},
            {"name": "source", "label": "Source", "field": "source"},
            {"name": "detail", "label": "Assessment", "field": "detail"},
        ],
        rows=rows,
        pagination={"rowsPerPage": 6},
    ).classes("w-full")


def _build_candidate_lane(service: AgoraService, mission_id: str | None) -> None:
    _section(
        "Minority lane",
        "Mechanistically distinct ideas survive",
        "A supported minority is preserved even when correlated proposals dominate volume.",
    )
    minority = [
        card
        for card in service.idea_cards(mission_id)
        if card.minority_preserved
    ] if mission_id else []
    if not minority:
        ui.label("No preserved minority candidate has reached formalization.").classes("agora-muted")
        return
    for card in minority:
        ui.label(card.core_mechanism).classes("text-body2 agora-body")
        ui.label(
            f"{card.novelty_status.value} · confidence {card.confidence:.2f} · {card.cluster_id}"
        ).classes("text-caption agora-muted")


def _build_candidate_comparison(service: AgoraService, mission_id: str | None) -> None:
    _section(
        "Candidate laboratory",
        "Specifications, receipts, and attribution",
        "Sandbox success produces a handoff. It never patches the primary repository.",
    )
    candidates = service.candidates(mission_id) if mission_id else ()
    experiments = service.experiments(mission_id) if mission_id else ()
    experiment_by_candidate = {item.candidate_id: item for item in experiments}
    rows = [
        {
            "candidate": candidate.candidate_id,
            "dependencies": len(candidate.external_dependencies),
            "experiment": (
                experiment_by_candidate[candidate.candidate_id].status
                if candidate.candidate_id in experiment_by_candidate
                else "NOT_RUN"
            ),
            "differential": (
                "MATCH"
                if candidate.candidate_id in experiment_by_candidate
                and experiment_by_candidate[candidate.candidate_id].differential_match
                else "UNPROVEN"
            ),
        }
        for candidate in candidates
    ]
    if not rows:
        ui.label("No formal CandidateSpecs yet.").classes("agora-muted")
        return
    ui.table(
        columns=[
            {"name": "candidate", "label": "Candidate", "field": "candidate"},
            {"name": "dependencies", "label": "External deps", "field": "dependencies", "sortable": True},
            {"name": "experiment", "label": "Experiment", "field": "experiment", "sortable": True},
            {"name": "differential", "label": "Independent match", "field": "differential"},
        ],
        rows=rows,
        row_key="candidate",
    ).classes("w-full")


def _build_attribution(service: AgoraService, mission_id: str | None) -> None:
    _section(
        "Attribution history",
        "Measured credit, not rhetorical credit",
        "Routing updates from downstream verification, minority rescue, hallucination, and quota efficiency.",
    )
    rows = _event_rows(service, mission_id, "outcome_attributed", "attribution") if mission_id else []
    if not rows:
        ui.label("Attribution appears only after a measured experiment and final decision.").classes(
            "agora-muted"
        )
        return
    ui.table(
        columns=[
            {"name": "candidate_id", "label": "Candidate", "field": "candidate_id"},
            {"name": "promotion_result", "label": "Result", "field": "promotion_result"},
            {"name": "measured_value", "label": "Measured value", "field": "measured_value", "sortable": True},
            {"name": "created_at", "label": "Recorded", "field": "created_at", "sortable": True},
        ],
        rows=rows,
        row_key="candidate_id",
    ).classes("w-full")


def build_agora_panel() -> None:
    """Render the Agora surface without modifying the rest of the dashboard."""
    ui.add_css(AGORA_CSS)
    try:
        service = AgoraService.create_default()
        snapshot = service.snapshot(event_limit=500)
    except (AgoraError, OSError, ValueError) as exc:
        with ui.element("section").classes("agora-shell w-full"):
            ui.label("Agora initialization blocked").classes("agora-title")
            ui.label(str(exc)).classes("agora-muted")
        return
    mission_id = _latest_mission_id(snapshot)
    with ui.element("section").classes("agora-shell w-full").props(
        'aria-label="Doofus Agora operator console"'
    ):
        with ui.row().classes("w-full items-start justify-between gap-4 q-mb-lg"):
            with ui.column().classes("gap-2"):
                ui.label("DOOFUS AGORA / FRONTIER V1+").classes("agora-kicker")
                ui.label("Invention with receipts. Debate without consensus theater.").classes(
                    "agora-title"
                )
                ui.label(
                    "Attended provider collection · blind critique · evidence fabric · "
                    "disposable code laboratory · bounded learning"
                ).classes("agora-muted")
            with ui.column().classes("items-end gap-2"):
                ui.label("ATTENDED OPERATIONAL").classes("agora-status")
                ui.label("AUTHORITY: CANDIDATE HANDOFF ONLY").classes("text-caption agora-muted")
                ui.button("Refresh Agora", on_click=ui.navigate.reload).props("outline")
        with ui.element("div").classes("agora-grid"):
            with ui.card().classes("agora-card agora-span-5"):
                _build_mission_composer(service)
            with ui.card().classes("agora-card agora-span-7"):
                _build_provider_matrix(snapshot)
            with ui.card().classes("agora-card agora-span-8"):
                _build_flow(service, mission_id)
            with ui.card().classes("agora-card agora-span-4"):
                _build_candidate_lane(service, mission_id)
            with ui.card().classes("agora-card agora-span-7"):
                _build_mission_evidence(service, mission_id)
            with ui.card().classes("agora-card agora-span-5"):
                _build_candidate_comparison(service, mission_id)
            with ui.card().classes("agora-card agora-span-12"):
                _build_attribution(service, mission_id)
