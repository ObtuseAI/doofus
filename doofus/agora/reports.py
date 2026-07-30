"""Mission reports and reproducibility capsules."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from doofus.agora.storage import AgoraRepository, canonical_json


def _public_event(event: dict[str, Any]) -> dict[str, Any] | None:
    if event["event_type"] == "alias_map_created":
        return None
    payload = dict(event["payload"])
    if event["event_type"] == "mission_created":
        mission = dict(payload["mission"])
        mission["context"] = "[SANITIZED_CONTEXT_FROZEN_IN_LOCAL_VAULT]"
        payload["mission"] = mission
    if event["event_type"] == "response_imported":
        response = dict(payload["response"])
        response["raw_output_path"] = "[LOCAL_CONTENT_ADDRESSED_VAULT]"
        payload["response"] = response
    return {
        "sequence": event["sequence"],
        "event_id": event["event_id"],
        "event_type": event["event_type"],
        "payload": payload,
        "event_hash": event["event_hash"],
        "created_at": event["created_at"],
    }


def build_report_payload(
    mission_id: str,
    repository: AgoraRepository,
    configuration_hashes: dict[str, str],
) -> dict[str, Any]:
    events = repository.mission_events(mission_id)
    public_events = tuple(
        public for event in events if (public := _public_event(event)) is not None
    )
    artifact_hashes = sorted(
        {
            value
            for event in public_events
            for value in _find_hashes(event["payload"])
        }
    )
    mission_event = next(
        (event for event in public_events if event["event_type"] == "mission_created"),
        None,
    )
    if mission_event is None:
        raise ValueError(f"cannot report unknown mission: {mission_id}")
    chain = repository.verify_event_chain()
    return {
        "schema_version": "1.0.0",
        "mission_id": mission_id,
        "mission": mission_event["payload"]["mission"],
        "stage": _latest_stage(public_events),
        "events": public_events,
        "configuration_hashes": configuration_hashes,
        "artifact_hashes": artifact_hashes,
        "routing_seed": mission_event["payload"]["mission"]["routing_seed"],
        "event_chain": chain,
        "authority_effect": "PROPOSALS_AND_HANDOFFS_ONLY_EXISTING_DOOFUS_GATES_REMAIN_AUTHORITATIVE",
    }


def _find_hashes(value: Any) -> tuple[str, ...]:
    hashes: list[str] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            if key.endswith("sha256") and isinstance(nested, str) and len(nested) == 64:
                hashes.append(nested)
            hashes.extend(_find_hashes(nested))
    elif isinstance(value, (list, tuple)):
        for nested in value:
            hashes.extend(_find_hashes(nested))
    return tuple(hashes)


def _latest_stage(events: tuple[dict[str, Any], ...]) -> str:
    stages = [
        str(event["payload"]["stage"])
        for event in events
        if event["event_type"] == "mission_stage"
    ]
    return stages[-1] if stages else "DRAFT"


def render_markdown_report(payload: dict[str, Any]) -> str:
    mission = payload["mission"]
    events = payload["events"]
    counts: dict[str, int] = {}
    for event in events:
        counts[event["event_type"]] = counts.get(event["event_type"], 0) + 1
    decisions = [
        event["payload"]["decision"]
        for event in events
        if event["event_type"] == "decision_recorded"
    ]
    minority = [
        event["payload"]["idea"]
        for event in events
        if event["event_type"] == "idea_formalized"
        and event["payload"]["idea"]["minority_preserved"]
    ]
    lines = [
        f"# Agora Mission {payload['mission_id']}",
        "",
        f"**Objective:** {mission['objective']}",
        "",
        f"**Stage:** `{payload['stage']}`",
        "",
        f"**Authority:** `{payload['authority_effect']}`",
        "",
        "## Reproducibility",
        "",
        f"- Routing seed: `{payload['routing_seed']}`",
        f"- Event-chain head: `{payload['event_chain']['head_hash']}`",
        f"- Event count: {payload['event_chain']['event_count']}",
        f"- Frozen artifact hashes: {len(payload['artifact_hashes'])}",
        "",
        "## Debate and evidence fabric",
        "",
    ]
    lines.extend(f"- {event_type}: {count}" for event_type, count in sorted(counts.items()))
    lines.extend(["", "## Preserved minority lane", ""])
    if minority:
        lines.extend(
            f"- `{idea['idea_id']}` — {idea['core_mechanism']}"
            for idea in minority
        )
    else:
        lines.append("- No mechanistically distinct supported minority survived this mission.")
    lines.extend(["", "## Decision", ""])
    if decisions:
        decision = decisions[-1]
        lines.extend(
            [
                f"- Action: `{decision['action']}`",
                f"- Confidence: {decision['confidence']:.3f}",
                f"- Value of information: {decision['value_of_information']:.3f}",
                f"- Hard-gate failures: {', '.join(decision['hard_gate_failures']) or 'none'}",
                "- `ACT` means eligible for submission to existing Doofus gates only.",
            ]
        )
    else:
        lines.append("- No decision has been recorded.")
    lines.extend(
        [
            "",
            "## Honest limitations",
            "",
            "- Provider responses are attended imports and remain untrusted content.",
            "- Source existence alone does not make a claim supported.",
            "- Consumer-browser submission, scraping, and extraction are disabled.",
            "- Sandbox success produces a candidate handoff; it never modifies this repository.",
            "",
        ]
    )
    return "\n".join(lines)


def write_reports(
    mission_id: str,
    destination: Path,
    repository: AgoraRepository,
    configuration_hashes: dict[str, str],
) -> dict[str, str]:
    destination.mkdir(parents=True, exist_ok=True)
    payload = build_report_payload(mission_id, repository, configuration_hashes)
    json_text = json.dumps(payload, indent=2, sort_keys=True, default=str)
    markdown_text = render_markdown_report(payload)
    capsule = {
        "schema_version": payload["schema_version"],
        "mission_id": mission_id,
        "configuration_hashes": configuration_hashes,
        "artifact_hashes": payload["artifact_hashes"],
        "routing_seed": payload["routing_seed"],
        "event_chain": payload["event_chain"],
        "report_json_sha256": hashlib.sha256(json_text.encode("utf-8")).hexdigest(),
        "report_markdown_sha256": hashlib.sha256(markdown_text.encode("utf-8")).hexdigest(),
    }
    paths = {
        "json": destination / f"{mission_id}.json",
        "markdown": destination / f"{mission_id}.md",
        "capsule": destination / f"{mission_id}.reproducibility.json",
    }
    paths["json"].write_text(json_text, encoding="utf-8")
    paths["markdown"].write_text(markdown_text, encoding="utf-8")
    paths["capsule"].write_text(
        json.dumps(capsule, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    for report_kind, path in paths.items():
        repository.store_blob(f"mission_report_{report_kind}", path.read_bytes())
    return {key: str(value) for key, value in paths.items()}


def configuration_hashes(config_dir: Path) -> dict[str, str]:
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(config_dir.glob("agora_*.yaml"))
    }


def report_sha256(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
