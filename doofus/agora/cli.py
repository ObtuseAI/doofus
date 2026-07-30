"""Command-line operator interface for attended Doofus Agora missions."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from doofus.agora.contracts import TermsStatus
from doofus.agora.errors import AgoraError
from doofus.agora.service import AgoraService, file_sha256


def _mapping_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"mission input file does not exist: {path}")
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"mission input must be a YAML or JSON mapping: {path}")
    return payload


def _emit(payload: Any) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="doofus-agora",
        description="Attended, evidence-gated invention and debate swarms.",
    )
    parser.add_argument("--config-dir", type=Path)
    parser.add_argument("--runtime-root", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("provider-status", help="Show provider, terms, and mission state.")

    create = commands.add_parser("mission-create", help="Create, sanitize, and compile a mission.")
    create.add_argument("--mission", type=Path, required=True)
    create.add_argument("--operator-approved", action="store_true")

    status = commands.add_parser("mission-status", help="Show one mission state.")
    status.add_argument("--mission-id", required=True)

    export = commands.add_parser("packet-export", help="Export pending attended prompt packets.")
    export.add_argument("--mission-id", required=True)
    export.add_argument("--destination", type=Path, required=True)

    response = commands.add_parser("response-import", help="Import an attended response as inert content.")
    response.add_argument("--packet-id", required=True)
    response.add_argument("--response", type=Path, required=True)

    advance = commands.add_parser("round-advance", help="Advance one fully collected debate round.")
    advance.add_argument("--mission-id", required=True)

    evidence = commands.add_parser("evidence-verify", help="Verify claims and prior art.")
    evidence.add_argument("--mission-id", required=True)

    experiment = commands.add_parser("sandbox-execute", help="Run two independent candidate implementations.")
    experiment.add_argument("--mission-id", required=True)
    experiment.add_argument("--candidate-id", required=True)
    experiment.add_argument("--implementation-a", type=Path, required=True)
    experiment.add_argument("--implementation-b", type=Path, required=True)
    experiment.add_argument("--provider-a", required=True)
    experiment.add_argument("--provider-b", required=True)
    experiment.add_argument("--test-provider", required=True)
    experiment.add_argument("--baseline-score", type=float, required=True)

    decision = commands.add_parser("decision-build", help="Build the gated decision and attribution.")
    decision.add_argument("--mission-id", required=True)
    decision.add_argument("--value-of-information", type=float, required=True)
    decision.add_argument("--apply-learning", action="store_true")

    refresh = commands.add_parser("terms-refresh", help="Refresh and hash one terms source.")
    refresh.add_argument("--provider-id", required=True)

    terms = commands.add_parser("terms-review", help="Record an explicit operator terms decision.")
    terms.add_argument("--provider-id", required=True)
    terms.add_argument("--reviewer", required=True)
    terms.add_argument(
        "--status",
        choices=tuple(status.value for status in TermsStatus),
        required=True,
    )
    terms.add_argument("--automated-submit-allowed", action="store_true")
    terms.add_argument("--automated-extract-allowed", action="store_true")
    terms.add_argument("--notes", required=True)

    report = commands.add_parser("report-generate", help="Generate JSON, Markdown, and replay capsule.")
    report.add_argument("--mission-id", required=True)
    report.add_argument("--destination", type=Path, required=True)

    problems = commands.add_parser(
        "problem-foundry",
        help="Collect a diverse ProblemCard portfolio from declared observations and rejections.",
    )
    problems.add_argument("--mission-id", required=True)
    problems.add_argument("--observations", type=Path, required=True)
    problems.add_argument("--maximum-cards", type=int, required=True)

    return parser


def _execute(args: argparse.Namespace, service: AgoraService) -> Any:
    if args.command == "provider-status":
        return service.snapshot(event_limit=500)
    if args.command == "mission-create":
        mission = service.create_mission(
            _mapping_file(args.mission),
            operator_approved=bool(args.operator_approved),
        )
        return {
            "mission": mission.model_dump(mode="json"),
            "stage": service.current_stage(mission.mission_id).value,
            "packet_count": len(service.packets(mission.mission_id)),
        }
    if args.command == "mission-status":
        mission = service.mission(args.mission_id)
        return {
            "mission": mission.model_dump(mode="json"),
            "stage": service.current_stage(args.mission_id).value,
            "packets": len(service.packets(args.mission_id)),
            "responses": len(service.responses(args.mission_id)),
            "ideas": len(service.idea_cards(args.mission_id)),
            "candidates": len(service.candidates(args.mission_id)),
            "experiments": len(service.experiments(args.mission_id)),
        }
    if args.command == "packet-export":
        return service.export_packets(args.mission_id, args.destination)
    if args.command == "response-import":
        text = args.response.read_text(encoding="utf-8")
        artifact = service.import_response_text(args.packet_id, text)
        return {
            "response": artifact.model_dump(mode="json"),
            "input_sha256": file_sha256(args.response),
        }
    if args.command == "round-advance":
        return service.advance_round(args.mission_id)
    if args.command == "evidence-verify":
        return tuple(
            card.model_dump(mode="json")
            for card in service.verify_evidence(args.mission_id)
        )
    if args.command == "sandbox-execute":
        result = service.run_experiment(
            mission_id=args.mission_id,
            candidate_id=args.candidate_id,
            implementation_sources=(
                args.implementation_a.read_text(encoding="utf-8"),
                args.implementation_b.read_text(encoding="utf-8"),
            ),
            implementation_provider_ids=(args.provider_a, args.provider_b),
            test_provider_id=args.test_provider,
            baseline_score=args.baseline_score,
        )
        return result.model_dump(mode="json")
    if args.command == "decision-build":
        decision, attributions = service.decide_and_attribute(
            mission_id=args.mission_id,
            value_of_information=args.value_of_information,
            apply_learning=bool(args.apply_learning),
        )
        return {
            "decision": decision.model_dump(mode="json"),
            "attributions": tuple(
                attribution.model_dump(mode="json")
                for attribution in attributions
            ),
        }
    if args.command == "terms-refresh":
        return service.refresh_terms(args.provider_id).model_dump(mode="json")
    if args.command == "terms-review":
        return service.review_terms(
            provider_id=args.provider_id,
            reviewer=args.reviewer,
            status=TermsStatus(args.status),
            automated_submit_allowed=bool(args.automated_submit_allowed),
            automated_extract_allowed=bool(args.automated_extract_allowed),
            notes=args.notes,
        ).model_dump(mode="json")
    if args.command == "report-generate":
        return service.generate_reports(args.mission_id, args.destination)
    if args.command == "problem-foundry":
        payload = _mapping_file(args.observations)
        return service.build_problem_portfolio(
            args.mission_id,
            {
                str(category): tuple(dict(item) for item in observations)
                for category, observations in payload.items()
            },
            args.maximum_cards,
        )
    raise ValueError(f"unsupported command: {args.command}")


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    try:
        service = AgoraService.create_default(
            config_dir=args.config_dir,
            runtime_root=args.runtime_root,
        )
        _emit(_execute(args, service))
    except (AgoraError, FileNotFoundError, OSError, ValidationError, ValueError) as exc:
        parser.exit(2, f"doofus-agora error: {exc}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
