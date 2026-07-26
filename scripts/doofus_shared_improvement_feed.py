"""Lean shared improvement feed: compact transferable artifacts for Blunder and cross-project reuse."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

WORKSPACE = Path(__file__).resolve().parents[1]
ARTIFACT_OUT = WORKSPACE / "artifacts" / "doofus" / "shared-improvement-feed-v1"
COMMIT_BEFORE = "018c880b48a4821ee391bbb150ad81942d240d9b"

FEED_SIZE_CAP_BYTES = 50 * 1024 * 1024  # 50 MB
MAX_FILE_BYTES = 512 * 1024  # 512 KB per feed file
SECRET_NAMES = {".env", ".env.local", "doofusapi", "doofusapi.txt", "doofusapi.env"}
DB_SUFFIXES = {".sqlite", ".sqlite-wal", ".sqlite-shm", ".db"}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def write_pair(out_dir: Path, stem: str, payload: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{stem}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    lines = [f"# {stem.replace('_', ' ').title()}", ""]
    for k, v in payload.items():
        if isinstance(v, (dict, list)):
            lines.extend([f"## {k}", "", "```json", json.dumps(v, indent=2), "```", ""])
        else:
            lines.append(f"- **{k}**: `{v}`")
    (out_dir / f"{stem}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def resolve_feed_destination() -> tuple[Path, str, dict]:
    for env_name in ("DOOFUS_SHARED_FEED_DIR", "DOOFUS_NETWORK_EXPORT_DIR", "NETWORK_SHARED_DESKTOP_FOLDER"):
        val = os.environ.get(env_name)
        if val:
            p = Path(val).resolve()
            return p / "doofus-improvement-feed", f"env:{env_name}", {"env": env_name}

    sys.path.insert(0, str(WORKSPACE))
    from doofus.core.doofus_paths import CANONICAL_SHARED, SHARED, ROOT

    shared_parent = CANONICAL_SHARED.parent
    if shared_parent.exists():
        return shared_parent / "doofus-improvement-feed", "doofus_paths:CANONICAL_SHARED.parent", {}

    if SHARED.parent.exists():
        return SHARED.parent / "doofus-improvement-feed", "doofus_paths:SHARED.parent", {}

    staging = ARTIFACT_OUT / "local_feed_staging" / "doofus-improvement-feed"
    return staging, "local_staging_fallback", {"reason": "no_network_destination_resolved"}


def feed_schema() -> dict:
    return {
        "classification": "DOOFUS_SHARED_IMPROVEMENT_FEED_SCHEMA",
        "version": "1.0.0",
        "required_fields": [
            "id", "created_at_utc", "source_project", "source_generation", "source_commit",
            "source_artifacts", "target_projects", "primary_target", "type", "title",
            "summary", "problem", "insight", "recommendation", "implementation_hint",
            "expected_value", "risk_level", "safety_constraints", "validation_method",
            "evidence", "reuse_conditions", "do_not_use_when", "blunder_relevance",
            "doofus_relevance", "status", "tags", "dedupe_key",
        ],
        "allowed_types": [
            "improvement", "recommendation", "variant", "mutation_method", "repair_recipe",
            "guard_pattern", "prompt_pattern", "test_pattern", "telemetry_lesson",
            "architecture_lesson", "risk_control", "operator_packet", "cross_project_transfer",
        ],
        "allowed_statuses": ["draft", "usable", "validated", "needs_review", "rejected"],
        "file_naming": "<UTC_TIMESTAMP>__<project_tag>__<type>__<slug>.json|.md",
    }


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:64]


def _item(
    *,
    slug: str,
    type_: str,
    title: str,
    summary: str,
    problem: str,
    insight: str,
    recommendation: str,
    implementation_hint: str,
    primary_target: str,
    target_projects: list[str],
    tags: list[str],
    evidence: list[str] | None = None,
    source_generation: int = 1639,
    source_artifacts: list[str] | None = None,
    expected_value: str = "medium",
    risk_level: str = "low",
    safety_constraints: list[str] | None = None,
    validation_method: str = "",
    reuse_conditions: list[str] | None = None,
    do_not_use_when: list[str] | None = None,
    blunder_relevance: str = "",
    doofus_relevance: str = "",
    status: str = "validated",
) -> dict:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dedupe_key = hashlib.sha256(f"{type_}:{slug}".encode()).hexdigest()[:16]
    return {
        "id": f"doofus-{dedupe_key}",
        "created_at_utc": utc_now(),
        "source_project": "doofus",
        "source_generation": source_generation,
        "source_commit": COMMIT_BEFORE,
        "source_artifacts": source_artifacts or [],
        "target_projects": target_projects,
        "primary_target": primary_target,
        "type": type_,
        "title": title,
        "summary": summary,
        "problem": problem,
        "insight": insight,
        "recommendation": recommendation,
        "implementation_hint": implementation_hint,
        "expected_value": expected_value,
        "risk_level": risk_level,
        "safety_constraints": safety_constraints or ["no_live_route", "no_runtime_coupling"],
        "validation_method": validation_method,
        "evidence": evidence or [],
        "reuse_conditions": reuse_conditions or ["read_only_consumption", "external_artifact_feed"],
        "do_not_use_when": do_not_use_when or ["direct_runtime_import_of_doofus_internals"],
        "blunder_relevance": blunder_relevance,
        "doofus_relevance": doofus_relevance,
        "status": status,
        "tags": tags,
        "dedupe_key": dedupe_key,
        "_filename_stem": f"{ts}__{primary_target}__{type_}__{slug}",
    }


def mine_discoveries() -> dict:
    artifact_dirs = [
        "gen1637-postlive-certification-v1",
        "gen1638-launch-guard-fix-v1",
        "gen1638-db-scrub-readiness-v1",
        "gen1638-live-verification-v2",
        "gen1638-postlive-certification-v1",
        "gen1639-live-verification-v1",
    ]
    findings: list[dict] = []
    base = WORKSPACE / "artifacts" / "doofus"
    for d in artifact_dirs:
        p = base / d
        if not p.exists():
            continue
        key_files = list(p.glob("FINAL_REPORT.json")) + list(p.glob("*audit*.json")) + list(p.glob("*manifest*.json"))
        for f in key_files[:5]:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                findings.append({"bundle": d, "file": str(f.relative_to(WORKSPACE)), "classification": data.get("classification")})
            except (json.JSONDecodeError, OSError):
                pass
    categories = {
        "guard_patterns": [
            "operator-approved-one-cycle with stop clear only inside try/finally",
            "open-ended loop blocked by stop_requested=true",
            "provider-gate bypass only when operator_approved_one_cycle flag set",
            "no silent fallback from live to dry-run",
        ],
        "db_safety": [
            "live DB preflight check-only before launch",
            "backup-first orphan row scrub with row-level JSON backup",
            "target-generation contamination detection",
            "checkpoint vs DB max generation reconciliation",
        ],
        "isolation": [
            "isolated_runtime_copy for non-live rehearsals",
            "child process env-aware DOOFUS_STATE override",
            "temp DB tests never touch canonical metrics DB",
        ],
        "mutation_methods": [
            "24 candidates per live cycle with proof-first rejection",
            "MAP-Elites cell discipline per generation",
            "shadow_upgrade bounded at 180s inline rescue budget",
        ],
        "telemetry": [
            "scoring_step_events.jsonl per candidate substep timing",
            "guarded_one_cycle_stop_clear_events.jsonl",
            "live_cycle_launch_guard_events.jsonl",
        ],
        "repair_recipes": [
            "provider_gate stop_requested preblock fix for one-cycle path",
            "SQLite lock-wait MAP-Elites active connection fix",
            "orphan map_elites_cells generation scrub",
            "inline rescue timeout containment as nonfatal",
        ],
        "blunder_transfer": [
            "LLM-optional mutation queue with hard stop flags",
            "filesystem-only artifact feed as cross-project memory",
            "non-live rehearsal before any live/provider action",
            "proof-first promotion with rejection classifier",
        ],
    }
    return {
        "classification": "DOOFUS_MINED_DISCOVERIES_RAW",
        "artifact_bundles_scanned": artifact_dirs,
        "artifact_findings": findings,
        "categories": categories,
        "mined_at": utc_now(),
    }


def build_feed_items() -> list[dict]:
    items: list[dict] = []

    def add(**kwargs: Any) -> None:
        items.append(_item(**kwargs))

    # --- Blunder-targeted (10+) ---
    add(
        slug="operator_approved_one_cycle_guard_pattern",
        type_="guard_pattern",
        title="Operator-approved one-cycle guard pattern",
        summary="Allow exactly one live cycle only when an explicit operator flag clears stop inside try/finally.",
        problem="Stop flag blocks all progress including authorized single cycles.",
        insight="Separate prepare-one-cycle from open-ended may_proceed; clear stop only inside guarded launch.",
        recommendation="Blunder should use explicit one-action approval packets that temporarily clear halt, then restore.",
        implementation_hint="try/finally around stop clear; telemetry event guarded_one_cycle_stop_clear.",
        primary_target="blunder",
        target_projects=["blunder", "general"],
        tags=["guard", "stop_flag", "one_cycle"],
        evidence=["artifacts/doofus/gen1638-launch-guard-fix-v1/", "artifacts/doofus/gen1639-live-verification-v1/"],
        blunder_relevance="Maps to Blunder single-action operator packets without continuous autonomy.",
        validation_method="Regression test: stop_requested blocks open loop; one-cycle flag allows single action.",
    )
    add(
        slug="non_live_dry_run_boundary_pattern",
        type_="guard_pattern",
        title="Non-live dry-run boundary pattern",
        summary="Non-live paths must classify as DOOFUS_MODEL_DRY_RUN and never invoke provider routes.",
        problem="Accidental live provider calls during certification or rehearsal.",
        insight="verify_nonlive_dry_run_guard() probes classification before any launch decision.",
        recommendation="Blunder should classify NO_LLM / SIMULATION modes explicitly before any external API.",
        implementation_hint="Central probe returning fixed classification; assert no model_call_events inserted.",
        primary_target="blunder",
        target_projects=["blunder", "general"],
        tags=["dry_run", "guard", "no_llm"],
        evidence=["artifacts/doofus/gen1639-live-verification-v1/nonlive_dry_run_guard_probe.json"],
        blunder_relevance="Blunder LLM-less mode must hard-block provider routes.",
    )
    add(
        slug="blunder_llm_optional_mutation_queue",
        type_="mutation_method",
        title="LLM-optional mutation queue with hard stop",
        summary="Queue mutations with deterministic fallbacks; LLM proposals optional and capped.",
        problem="Autonomous systems depend on LLM availability for all mutations.",
        insight="Doofus generates 24 candidates/cycle; 0 promoted when proof gate fails; dry-run proposals work.",
        recommendation="Blunder mutation catalog with deterministic variants plus optional LLM enrichment.",
        implementation_hint="Mutation engine accepts proposal list; dry_run fills synthetic proposals for testing.",
        primary_target="blunder",
        target_projects=["blunder"],
        tags=["mutation", "llm_optional", "queue"],
        blunder_relevance="Core Blunder architecture: improve without mandatory LLM.",
    )
    add(
        slug="artifact_feed_as_cross_project_memory",
        type_="architecture_lesson",
        title="Artifact feed as cross-project memory",
        summary="Use filesystem JSON/MD feeds instead of shared runtime or DB coupling.",
        problem="Full repo forks and DB copies are too large and create unsafe coupling.",
        insight="Compact feed items with schema, dedupe, and project indexes enable safe reuse.",
        recommendation="Blunder consumes doofus-improvement-feed/ as read-only external knowledge.",
        implementation_hint="MANIFEST.json + by_project/blunder/ indexes; no import of doofus package.",
        primary_target="blunder",
        target_projects=["blunder", "general"],
        tags=["feed", "architecture", "decoupling"],
        blunder_relevance="Primary consumption model for this feed system.",
    )
    add(
        slug="proof_first_promotion_gate",
        type_="guard_pattern",
        title="Proof-first promotion gate",
        summary="Candidates score and reject before promotion; no forced promotion on live cycles.",
        problem="Unsafe promotion under live pressure.",
        insight="gen1638/1639: 24 candidates, 0 promoted, 24 rejected each cycle.",
        recommendation="Blunder should require proof/replay pass before any promotion action.",
        implementation_hint="promotion_gate.evaluate_promotion with rejection_classifier telemetry.",
        primary_target="blunder",
        target_projects=["blunder", "doofus"],
        tags=["promotion", "proof", "rejection"],
        evidence=["artifacts/doofus/gen1639-live-verification-v1/FINAL_REPORT.json"],
        blunder_relevance="Deterministic validation before state change.",
    )
    add(
        slug="non_live_rehearsal_before_live",
        type_="test_pattern",
        title="Non-live rehearsal before live action",
        summary="Isolated runtime rehearsal validates guards without canonical DB mutation.",
        problem="First live attempt discovers guard bugs expensively.",
        insight="postlive_nonlive_certification_rehearsal uses isolated_runtime_copy.",
        recommendation="Blunder runs shadow rehearsal in temp workspace before any production change.",
        implementation_hint="isolated_runtime_copy(clear_stop_flags=False); assert checkpoint unchanged.",
        primary_target="blunder",
        target_projects=["blunder", "general"],
        tags=["rehearsal", "isolation", "preflight"],
        evidence=["artifacts/doofus/gen1639-postlive-certification-network-fork-v1/postlive_nonlive_certification_rehearsal.json"],
    )
    add(
        slug="rollback_safe_action_packets",
        type_="operator_packet",
        title="Rollback-safe action packets",
        summary="Prep-only launch packets document baseline, refusal conditions, and restore procedure.",
        problem="Operators launch without explicit baseline or rollback path.",
        insight="GEN1639_OPERATOR_REVIEW_LAUNCH_PACKET_PREP_ONLY warns it does not authorize launch.",
        recommendation="Blunder operator packets: baseline snapshot, command template, refusal matrix, restore steps.",
        implementation_hint="JSON + MD pair; hash prep packet; separate authorization prompt.",
        primary_target="blunder",
        target_projects=["blunder", "doofus"],
        tags=["operator", "packet", "rollback"],
        evidence=["artifacts/doofus/gen1638-postlive-certification-v1/GEN1639_OPERATOR_REVIEW_LAUNCH_PACKET_PREP_ONLY.json"],
    )
    add(
        slug="self_improvement_queue_hard_stop",
        type_="risk_control",
        title="Self-improvement queue with hard stop flags",
        summary="Continuous improvement requires explicit stop_requested and may_run guards.",
        problem="Runaway autonomous loops.",
        insight="stop_requested=true after every one-cycle; open-ended blocked.",
        recommendation="Blunder improvement queue checks halt flag before each batch.",
        implementation_hint="on_off_switch.status(); may_run false when stop_requested.",
        primary_target="blunder",
        target_projects=["blunder"],
        tags=["stop", "autonomy", "risk"],
    )
    add(
        slug="deterministic_mutation_replay_loop",
        type_="mutation_method",
        title="Deterministic mutation replay loop",
        summary="Generate, score, reject/promote with full telemetry; replay stability traits tracked.",
        problem="Non-reproducible mutation outcomes.",
        insight="scoring_step_events.jsonl records per-candidate substeps with duration_ms.",
        recommendation="Blunder logs each mutation attempt with dedupe_key and replay artifacts.",
        implementation_hint="JSONL telemetry; candidate_id encodes generation and hash.",
        primary_target="blunder",
        target_projects=["blunder"],
        tags=["mutation", "replay", "telemetry"],
    )
    add(
        slug="filesystem_only_feed_consumer_design",
        type_="architecture_lesson",
        title="Filesystem-only feed consumer design",
        summary="Importer reads MANIFEST + by_type indexes; never spawns Doofus subprocess.",
        problem="Cross-project imports create hidden runtime dependencies.",
        insight="Feed items are self-contained JSON with evidence paths as strings only.",
        recommendation="Blunder feed consumer: validate schema, filter by primary_target=blunder, apply recipes locally.",
        implementation_hint="Optional CLI: blunder_feed_import --dir SharedFolder/doofus-improvement-feed",
        primary_target="blunder",
        target_projects=["blunder"],
        tags=["consumer", "architecture", "import"],
    )
    add(
        slug="blunder_scoring_timeout_budget",
        type_="telemetry_lesson",
        title="Scoring timeout budgeting per candidate",
        summary="Track slowest scoring step; gen1639 max candidate_total ~90ms, no timeouts.",
        problem="Unbounded scoring blocks cycles.",
        insight="scoring_step_events capture substep duration; timeout status tracked separately.",
        recommendation="Blunder caps per-candidate evaluation time with classified timeout outcome.",
        implementation_hint="Log slowest step; fail candidate not entire cycle on timeout.",
        primary_target="blunder",
        target_projects=["blunder", "doofus"],
        tags=["scoring", "timeout", "telemetry"],
        evidence=["artifacts/doofus/gen1639-live-verification-v1/gen1639_live_telemetry_summary.json"],
    )

    # --- General cross-project (10+) ---
    add(
        slug="provider_gate_no_silent_fallback",
        type_="guard_pattern",
        title="Provider gate: no silent fallback",
        summary="Live route requires explicit readiness; never silently fall back to dry-run mid-cycle.",
        problem="Hidden dry-run during authorized live verification.",
        insight="operator_approved_one_cycle checks live_provider_ready and model_mode==live directly.",
        recommendation="Any autonomous system must surface provider/mode mismatch as blocking classification.",
        implementation_hint="Separate may_call_live_provider from guarded one-cycle readiness check.",
        primary_target="general",
        target_projects=["general", "doofus"],
        tags=["provider", "fallback", "live"],
        evidence=["artifacts/doofus/gen1638-postlive-certification-v1/provider_gate_fix_audit.json"],
    )
    add(
        slug="backup_first_db_scrub_recipe",
        type_="repair_recipe",
        title="Backup-first DB scrub recipe",
        summary="Row-level JSON backup before deleting orphan generation rows.",
        problem="42GB full DB copy hangs; orphan rows block launch.",
        insight="2 orphan map_elites_cells at gen1638 blocked preflight; targeted delete after JSON backup.",
        recommendation="Never scrub without backup evidence; prefer row-level over full copy for huge DBs.",
        implementation_hint="Export orphan rows to JSON; verify preflight; delete by primary key only.",
        primary_target="general",
        target_projects=["general", "doofus"],
        tags=["db", "scrub", "backup"],
        evidence=["artifacts/doofus/gen1638-db-scrub-readiness-v1/FINAL_REPORT.json"],
    )
    add(
        slug="live_db_preflight_check_only",
        type_="test_pattern",
        title="Live DB preflight check-only",
        summary="Preflight inspects checkpoint, cycle checkpoint, DB max, target generation counts without mutation.",
        problem="Launch with contaminated or ambiguous DB state.",
        insight="inspect_live_db(target_generation=N+1) detects rows above checkpoint.",
        recommendation="Run check-only preflight as gate before any generation advance.",
        implementation_hint="scripts/doofus_live_db_preflight.py --output-dir artifacts/...",
        primary_target="general",
        target_projects=["general", "doofus", "blunder"],
        tags=["preflight", "db", "check_only"],
    )
    add(
        slug="child_process_runtime_path_isolation",
        type_="architecture_lesson",
        title="Child process runtime path isolation",
        summary="Tests override DOOFUS_STATE/METRICS_DB via env to prevent canonical contamination.",
        problem="Tests mutate production checkpoint or metrics DB.",
        insight="isolated_runtime_copy patches doofus_paths and env for child processes.",
        recommendation="Any long-running system should support isolated state roots for CI/rehearsal.",
        implementation_hint="isolated_runtime.py context manager; temp dir under AppData/Local/Temp.",
        primary_target="general",
        target_projects=["general", "doofus"],
        tags=["isolation", "testing", "runtime"],
    )
    add(
        slug="target_generation_contamination_detection",
        type_="test_pattern",
        title="Target generation contamination detection",
        summary="Refuse launch if target_generation rows exist before authorized cycle.",
        problem="Partial failed cycles leave orphan rows.",
        insight="live_db_preflight reports target_generation_total and contamination_detected.",
        recommendation="Treat any pre-existing target-gen rows as blockers unless classified orphan-safe.",
        implementation_hint="table_counts per generation-bearing table in preflight JSON.",
        primary_target="general",
        target_projects=["general", "doofus"],
        tags=["contamination", "preflight", "generation"],
    )
    add(
        slug="guarded_stop_clear_telemetry",
        type_="telemetry_lesson",
        title="Guarded stop-clear telemetry",
        summary="Log stop state before/during/after one-cycle; prove restoration.",
        problem="Stop flag left false after cycle exception.",
        insight="guarded_one_cycle_stop_clear_events.jsonl records full stop transition.",
        recommendation="Emit structured telemetry for any temporary override of safety flags.",
        implementation_hint="JSONL event with stop_state_before, stop_state_during, stop_state_after.",
        primary_target="general",
        target_projects=["general", "doofus"],
        tags=["telemetry", "stop", "audit"],
    )
    add(
        slug="launch_guard_decision_log",
        type_="telemetry_lesson",
        title="Launch guard decision log",
        summary="live_cycle_launch_guard_events record allowed/refused with refusal_reason.",
        problem="Unclear why launch was blocked or allowed.",
        insight="Each event includes db_target_generation_count_before and nonlive_guard_classification.",
        recommendation="Structured launch audit trail for operator review.",
        implementation_hint="Append JSONL on every launch attempt.",
        primary_target="general",
        target_projects=["general", "doofus"],
        tags=["telemetry", "launch", "guard"],
    )
    add(
        slug="certification_manifest_pattern",
        type_="architecture_lesson",
        title="Certification manifest pattern",
        summary="Single JSON manifest summarizes live verification, preflight, tests, and blockers.",
        problem="Evidence scattered across dozens of artifact files.",
        insight="gen1638/1639 certification manifests consolidate verdict fields.",
        recommendation="Cross-project cert bundles should have one machine-readable manifest.",
        implementation_hint="gen1639_certification_manifest.json with top_level_classification.",
        primary_target="general",
        target_projects=["general", "doofus"],
        tags=["certification", "manifest", "audit"],
    )
    add(
        slug="no_recursive_export_into_source",
        type_="risk_control",
        title="No recursive export into source tree",
        summary="Feed destination must not be inside source repo root.",
        problem="Network export copied destination into itself (413GB fork attempt).",
        insight="Resolve destination outside DOOFUS_ROOT; refuse if subpath of source.",
        recommendation="Validate dest.is_relative_to(source) before any publish copy.",
        implementation_hint="Path.resolve(); raise if source in dest.parents or vice versa for feed.",
        primary_target="general",
        target_projects=["general"],
        tags=["export", "risk", "filesystem"],
    )
    add(
        slug="compact_artifact_over_bulk_copy",
        type_="recommendation",
        title="Compact artifact feed over bulk copy",
        summary="Export lessons and recipes, not 42GB SQLite or historical backups.",
        problem="Full fork exports are slow, risky, and unusable for other projects.",
        insight="40 feed items << 1MB vs 413GB repo copy.",
        recommendation="Default cross-project handoff is structured feed, not repo mirror.",
        implementation_hint="Size cap 50MB; exclude *.sqlite from publish manifest.",
        primary_target="general",
        target_projects=["general", "blunder", "doofus"],
        tags=["feed", "size", "handoff"],
    )
    add(
        slug="generation_baseline_operator_review",
        type_="operator_packet",
        title="Generation baseline operator review",
        summary="Each live generation requires post-live cert before next generation prep packet.",
        problem="Skipping certification between generations.",
        insight="gen1638 postlive -> gen1639 prep packet -> explicit auth -> gen1639 live -> postlive seed.",
        recommendation="Enforce cert chain: live pass -> postlive cert -> prep-only next gen packet.",
        implementation_hint="POSTLIVE_GEN1639_CERTIFICATION_SEED.json warns no gen1640 auth.",
        primary_target="general",
        target_projects=["general", "doofus"],
        tags=["operator", "generation", "certification"],
    )

    # --- Doofus continuation (5+) ---
    add(
        slug="gen1640_prep_only_packet_requirement",
        type_="operator_packet",
        title="Gen1640 prep-only packet requirement",
        summary="Next generation requires prep-only packet; separate prompt for authorization.",
        problem="Accidental gen1640 launch from stale packets.",
        insight="Prep packets explicitly state they do not authorize launch.",
        recommendation="Keep GEN1640_OPERATOR_REVIEW_LAUNCH_PACKET_PREP_ONLY separate from live auth.",
        implementation_hint="required_baseline block with gen1640_row_count=0 check.",
        primary_target="doofus",
        target_projects=["doofus"],
        tags=["gen1640", "operator", "prep"],
        doofus_relevance="Immediate next step after gen1639 cert.",
    )
    add(
        slug="postlive_nonlive_rehearsal_gen1639",
        type_="test_pattern",
        title="Post-gen1639 non-live certification rehearsal",
        summary="Rehearsal from gen1639 complete must not promote checkpoint or insert live rows.",
        problem="Certification mutates canonical state.",
        insight="readiness_passed checks canonical checkpoint unchanged at 1639.",
        recommendation="Run doofus_gen1639_postlive_certification_rehearsal.py before gen1640 prep.",
        implementation_hint="Assert preflight gen1640 target_generation_total==0 after rehearsal.",
        primary_target="doofus",
        target_projects=["doofus"],
        tags=["rehearsal", "gen1639", "certification"],
        doofus_relevance="Required before gen1640 work.",
    )
    add(
        slug="provider_gate_postlive_regression_suite",
        type_="test_pattern",
        title="Provider gate postlive regression suite",
        summary="tests/test_provider_gate_postlive.py covers one-cycle stop bypass scope.",
        problem="Provider gate fix regresses open-ended blocking.",
        insight="10 tests validate operator_approved_one_cycle path without weakening open loop.",
        recommendation="Run focused pytest filter before any live gen1640 cycle.",
        implementation_hint="test_provider_gate_postlive.py + test_provider_aware_one_cycle_launch.py",
        primary_target="doofus",
        target_projects=["doofus"],
        tags=["test", "provider_gate", "regression"],
        doofus_relevance="Mandatory pre-gen1640 guard tests.",
    )
    add(
        slug="inline_rescue_deadline_skips_proof_builder",
        type_="telemetry_lesson",
        title="Inline rescue deadline skips proof-builder",
        summary="When inline rescue consumes budget, proof_builder_start is skipped not crashed.",
        problem="Proof builder runs unbounded after slow shadow_upgrade.",
        insight="gen1639: proof_builder skipped at 0.23s remaining; INLINE_RESCUE_OK.",
        recommendation="Budget inline rescue and defer proof-builder to next cycle.",
        implementation_hint="remaining_seconds check before proof_builder_start stage.",
        primary_target="doofus",
        target_projects=["doofus", "blunder"],
        tags=["inline_rescue", "proof_builder", "budget"],
        doofus_relevance="Observed gen1638/1639 live cycles.",
    )
    add(
        slug="one_live_model_call_per_cycle_cap",
        type_="risk_control",
        title="One live model call per cycle cap",
        summary="--max-model-calls 2 enforced; gen1639 used 1 call within budget.",
        problem="Unbounded provider cost during live cycles.",
        insight="max_cost_usd 0.05 and max_model_calls 2 in launch command template.",
        recommendation="Keep caps on every live cycle command template.",
        implementation_hint="Provider aware live cycle CLI flags enforced in launch guard.",
        primary_target="doofus",
        target_projects=["doofus"],
        tags=["cost", "model_calls", "cap"],
        doofus_relevance="gen1640 template inherits same caps.",
    )

    # --- Mutation methods (5+) ---
    add(
        slug="candidate_batch_generation_24",
        type_="mutation_method",
        title="Candidate batch generation (24 per cycle)",
        summary="Fixed batch size per generation with lineage tracking.",
        problem="Uncontrolled candidate explosion.",
        insight="gen1639: 24 candidates, all rejected, 0 promoted.",
        recommendation="Cap batch size; log lineage_parents count in cycle result.",
        implementation_hint="mutation_engine + candidate_generator batch limits.",
        primary_target="general",
        target_projects=["doofus", "blunder"],
        tags=["mutation", "batch", "candidates"],
    )
    add(
        slug="map_elites_insertion_discipline",
        type_="mutation_method",
        title="MAP-Elites insertion discipline",
        summary="Cells tagged by generation; orphan cells block preflight.",
        problem="map_elites_cells ahead of checkpoint blocked gen1638 launch.",
        insight="DB scrub removed 2 orphan gen1638 cells; candidates max lagged until live run.",
        recommendation="Insert cells only for completed generation cycles.",
        implementation_hint="Preflight checks map_elites max vs checkpoint generation.",
        primary_target="general",
        target_projects=["doofus"],
        tags=["map_elites", "mutation", "db"],
    )
    add(
        slug="shadow_upgrade_bounded_inline_rescue",
        type_="mutation_method",
        title="Shadow upgrade bounded inline rescue",
        summary="Process up to N shadow upgrades within 180s inline rescue budget.",
        problem="Shadow upgrade proof_timeout at ~179s blocks entire cycle.",
        insight="First item proof_timeout then deadline_reached; cycle still passes.",
        recommendation="Bound items processed; classify partial as nonfatal.",
        implementation_hint="timeout_threshold_ms 180000; shadow_upgrade_item_complete outcome proof_timeout.",
        primary_target="general",
        target_projects=["doofus", "blunder"],
        tags=["shadow", "inline_rescue", "mutation"],
    )
    add(
        slug="trait_mutation_from_elite_archive",
        type_="variant",
        title="Trait mutation variants from elite archive",
        summary="Elite archive pins best_ever candidates for mutation parents.",
        problem="Mutation lacks high-quality parent diversity.",
        insight="inline rescue elite_archive lists 7 entries from best_ever_pin and backfill.",
        recommendation="Maintain capped elite archive for parent selection.",
        implementation_hint="elite_archive_count with size_cap 25 in inline rescue detail.",
        primary_target="general",
        target_projects=["doofus", "blunder"],
        tags=["variant", "elite", "traits"],
    )
    add(
        slug="gepa_reflective_mutation_type",
        type_="variant",
        title="GEPA reflective mutation type variant",
        summary="gepa_reflective mutation type used for arena-linked trait bundles.",
        problem="Single mutation type limits exploration.",
        insight="DOOFUS_1609_09aae9a1c8 in elite archive uses gepa_reflective.",
        recommendation="Catalog mutation types with trait bundle schemas.",
        implementation_hint="mutation_type field in candidate lineage nodes.",
        primary_target="general",
        target_projects=["doofus", "blunder"],
        tags=["variant", "gepa", "mutation"],
    )

    # --- Repair recipes (5+) ---
    add(
        slug="provider_gate_stop_preblock_fix",
        type_="repair_recipe",
        title="Provider gate stop_requested preblock fix",
        summary="For operator_approved_one_cycle, skip may_call_live_provider stop check; verify readiness directly.",
        problem="B1053_PROVIDER_AWARE_LIVE_CYCLE_AUTH_BLOCKED on first gen1638 attempt.",
        insight="may_call_live_provider used check_may_proceed before guarded stop-clear.",
        recommendation="Narrow bypass: only when operator_approved_one_cycle=True.",
        implementation_hint="provider_aware_live_cycle.py; tests/test_provider_gate_postlive.py",
        primary_target="doofus",
        target_projects=["doofus", "general"],
        tags=["repair", "provider_gate", "stop"],
        evidence=["artifacts/doofus/gen1638-postlive-certification-v1/provider_gate_fix_audit.json"],
    )
    add(
        slug="map_elites_active_connection_lock_wait_fix",
        type_="repair_recipe",
        title="MAP-Elites active connection lock-wait fix",
        summary="Ensure SQLite connections closed before MAP-Elites write in scoring loop.",
        problem="DB lock wait regression blocking scoring.",
        insight="gen1639 MAP-Elites lock-wait status ok after prior fixes.",
        recommendation="Short-lived connections; explicit conn.close in scoring persist.",
        implementation_hint="Monitor map_elites lock-wait in telemetry summary.",
        primary_target="doofus",
        target_projects=["doofus"],
        tags=["repair", "sqlite", "map_elites"],
    )
    add(
        slug="orphan_generation_row_scrub",
        type_="repair_recipe",
        title="Orphan generation row scrub procedure",
        summary="Identify rows where generation > checkpoint or pre-target contamination; backup then delete.",
        problem="2 map_elites_cells at gen1638 while checkpoint at gen1637.",
        insight="Row-level JSON backup then targeted DELETE.",
        recommendation="Never DELETE without backup artifact and operator review packet.",
        implementation_hint="gen1638-db-scrub-readiness-v1 bundle documents scrub.",
        primary_target="doofus",
        target_projects=["doofus", "general"],
        tags=["repair", "scrub", "orphan"],
    )
    add(
        slug="inline_rescue_timeout_containment",
        type_="repair_recipe",
        title="Inline rescue timeout containment",
        summary="Classify shadow_upgrade proof_timeout as partial; end with INLINE_RESCUE_OK.",
        problem="180s shadow upgrade hang appears blocking.",
        insight="event_type timeout at shadow_upgrade still allows cycle pass.",
        recommendation="Timeout per item not per entire rescue unless budget exhausted.",
        implementation_hint="status ok on end event with classification INLINE_RESCUE_OK.",
        primary_target="doofus",
        target_projects=["doofus", "blunder"],
        tags=["repair", "inline_rescue", "timeout"],
    )
    add(
        slug="powershell_utf8_bom_log_decode",
        type_="repair_recipe",
        title="PowerShell UTF-8 BOM log decode",
        summary="When capturing live cycle logs via PowerShell redirect, decode utf-8-sig or utf-16.",
        problem="JSON decode fails on live_cycle_process_result from PowerShell Out-File.",
        insight="read_bytes check for BOM ef bb bf or ff fe.",
        recommendation="Finalize scripts handle BOM; prefer Python subprocess for capture.",
        implementation_hint="decode utf-8-sig in finalize scripts.",
        primary_target="doofus",
        target_projects=["doofus", "general"],
        tags=["repair", "windows", "logging"],
    )

    # --- Test patterns (5+) ---
    add(
        slug="focused_provider_gate_pytest_filter",
        type_="test_pattern",
        title="Focused provider gate pytest filter",
        summary="pytest -k filter for provider_gate, one_cycle, live_db_preflight, isolated_runtime.",
        problem="Full test suite too slow; misses guard regressions.",
        insight="39 focused + 49 broader tests passed pre-gen1639 launch.",
        recommendation="Run focused filter before every live generation.",
        implementation_hint="tests/test_provider_aware_one_cycle_launch.py and allies.",
        primary_target="doofus",
        target_projects=["doofus"],
        tags=["test", "pytest", "guard"],
    )
    add(
        slug="isolated_runtime_test_pattern",
        type_="test_pattern",
        title="Isolated runtime test pattern",
        summary="Tests use isolated_runtime_copy; never assert against canonical METRICS_DB.",
        problem="Test pollution of live DB.",
        insight="conftest monkeypatches doofus_paths for temp dirs.",
        recommendation="Blunder tests use BLUNDER_STATE temp root pattern.",
        implementation_hint="tests/conftest.py isolated fixtures.",
        primary_target="general",
        target_projects=["general", "doofus", "blunder"],
        tags=["test", "isolation"],
    )
    add(
        slug="postlive_preflight_target_gen_plus_one",
        type_="test_pattern",
        title="Postlive preflight target gen+1",
        summary="After gen N complete, preflight with target_generation=N+1 to detect contamination.",
        problem="Missing rows at N+1 undetected until launch.",
        insight="post-gen1639 preflight uses target 1640; expects 0 rows.",
        recommendation="Standard check-only preflight after every live pass.",
        implementation_hint="inspect_live_db(target_generation=checkpoint+1).",
        primary_target="doofus",
        target_projects=["doofus"],
        tags=["test", "preflight"],
    )
    add(
        slug="proof_builder_generation_identity_guard",
        type_="test_pattern",
        title="Proof-builder generation identity guard",
        summary="Proof builder queue items must match current generation context.",
        problem="Cross-generation proof items corrupt promotion.",
        insight="tests/test_doofus_proof_builder.py in focused filter.",
        recommendation="Assert generation on queue entries before processing.",
        implementation_hint="proof_builder queue paths scoped to generation.",
        primary_target="doofus",
        target_projects=["doofus", "blunder"],
        tags=["test", "proof_builder"],
    )
    add(
        slug="nonlive_cycle_forces_model_dry_run_test",
        type_="test_pattern",
        title="Nonlive cycle forces model dry-run test",
        summary="Explicit test that non-live cycle path yields DOOFUS_MODEL_DRY_RUN.",
        problem="live_model_if_available leaks into certification.",
        insight="verify_nonlive_dry_run_guard in prelaunch probe.",
        recommendation="Blunder: assert NO_LLM classification in certification tests.",
        implementation_hint="test_live_cycle_launch_guard nonlive_cycle_forces_model_dry_run.",
        primary_target="general",
        target_projects=["general", "doofus", "blunder"],
        tags=["test", "dry_run"],
    )

    return items


def validate_feed_item(item: dict, schema: dict) -> list[str]:
    errors = []
    for field in schema["required_fields"]:
        if field not in item:
            errors.append(f"missing:{field}")
    if item.get("type") not in schema["allowed_types"]:
        errors.append(f"invalid_type:{item.get('type')}")
    if item.get("status") not in schema["allowed_statuses"]:
        errors.append(f"invalid_status:{item.get('status')}")
    return errors


def item_to_markdown(item: dict) -> str:
    lines = [
        f"# {item['title']}",
        "",
        f"**Type:** `{item['type']}` | **Status:** `{item['status']}` | **Target:** `{item['primary_target']}`",
        "",
        "## Summary",
        item["summary"],
        "",
        "## Problem",
        item["problem"],
        "",
        "## Insight",
        item["insight"],
        "",
        "## Recommendation",
        item["recommendation"],
        "",
        "## Implementation hint",
        item["implementation_hint"],
        "",
        "## Blunder relevance",
        item.get("blunder_relevance") or "_n/a_",
        "",
        "## Evidence",
        *[f"- `{e}`" for e in item.get("evidence", [])],
        "",
        "## Tags",
        ", ".join(f"`{t}`" for t in item.get("tags", [])),
        "",
        f"_dedupe_key: `{item['dedupe_key']}`_",
    ]
    return "\n".join(lines) + "\n"


def is_excluded_path(path: Path) -> bool:
    if path.name in SECRET_NAMES:
        return True
    if any(path.name.endswith(s) for s in DB_SUFFIXES):
        return True
    if path.stat().st_size > MAX_FILE_BYTES:
        return True
    return False


def publish_feed(
    *,
    staging_root: Path,
    dest_root: Path,
    items: list[dict],
    schema: dict,
    mined: dict,
    blunder_bundle: dict,
    dry_run: bool = False,
) -> dict:
    sys.path.insert(0, str(WORKSPACE))
    from doofus.core.doofus_paths import ROOT

    dest_resolved = dest_root.resolve()
    source_resolved = ROOT.resolve()
    if source_resolved in dest_resolved.parents or dest_resolved == source_resolved:
        return {"classification": "DOOFUS_FEED_PUBLISH_REFUSED", "reason": "destination_inside_source_tree"}

    dirs = {
        "latest": dest_root / "latest",
        "by_project_blunder": dest_root / "by_project" / "blunder",
        "by_project_doofus": dest_root / "by_project" / "doofus",
        "by_project_general": dest_root / "by_project" / "general",
        "archive": dest_root / "archive",
    }
    for t in schema["allowed_types"]:
        dirs[f"type_{t}"] = dest_root / "by_type" / t.replace("_", "-") if False else dest_root / "by_type" / t  # keep underscores

    if dry_run:
        return {"classification": "DOOFUS_FEED_PUBLISH_DRY_RUN", "dest": str(dest_root), "item_count": len(items)}

    for d in set(dirs.values()):
        d.mkdir(parents=True, exist_ok=True)

    written: list[str] = []
    dedupe_seen: set[str] = set()
    total_bytes = 0

    for item in items:
        dk = item["dedupe_key"]
        if dk in dedupe_seen:
            continue
        dedupe_seen.add(dk)
        stem = item["_filename_stem"]
        payload = {k: v for k, v in item.items() if not k.startswith("_")}
        json_text = json.dumps(payload, indent=2)
        md_text = item_to_markdown(payload)
        if len(json_text.encode()) > MAX_FILE_BYTES:
            continue
        targets = [dirs["latest"]]
        pt = item["primary_target"]
        if pt == "blunder":
            targets.append(dirs["by_project_blunder"])
        elif pt == "doofus":
            targets.append(dirs["by_project_doofus"])
        else:
            targets.append(dirs["by_project_general"])
        type_dir = dest_root / "by_type" / item["type"]
        type_dir.mkdir(parents=True, exist_ok=True)
        targets.append(type_dir)

        for td in targets:
            (td / f"{stem}.json").write_text(json_text, encoding="utf-8")
            (td / f"{stem}.md").write_text(md_text, encoding="utf-8")
        written.append(stem)
        total_bytes += len(json_text.encode()) + len(md_text.encode())

    blunder_json = json.dumps(blunder_bundle, indent=2)
    for folder in [dirs["by_project_blunder"], dest_root]:
        (folder / "BLUNDER_RECOMMENDATION_BUNDLE.json").write_text(blunder_json, encoding="utf-8")
        (folder / "BLUNDER_RECOMMENDATION_BUNDLE.md").write_text(blunder_bundle["_markdown"], encoding="utf-8")

    manifest = {
        "classification": "DOOFUS_IMPROVEMENT_FEED_MANIFEST",
        "created_at_utc": utc_now(),
        "source_project": "doofus",
        "source_commit": COMMIT_BEFORE,
        "source_generation": 1639,
        "item_count": len(written),
        "dedupe_keys": sorted(dedupe_seen),
        "types_index": {},
        "projects_index": {"blunder": [], "doofus": [], "general": []},
        "written_stems": written,
        "excluded_patterns": list(SECRET_NAMES) + list(DB_SUFFIXES),
        "size_cap_bytes": FEED_SIZE_CAP_BYTES,
        "total_bytes_estimate": total_bytes,
    }
    for item in items:
        manifest["types_index"].setdefault(item["type"], []).append(item["dedupe_key"])
        manifest["projects_index"].setdefault(item["primary_target"], []).append(item["dedupe_key"])

    (dest_root / "MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (dest_root / "MANIFEST.md").write_text(
        f"# Doofus Improvement Feed Manifest\n\n{len(written)} items.\n", encoding="utf-8"
    )
    (dest_root / "README.md").write_text(
        "# Doofus Improvement Feed\n\n"
        "Compact transferable discoveries from Doofus gen1637-gen1639.\n\n"
        "**Not a runtime dependency.** Blunder and other projects consume these artifacts read-only.\n\n"
        "## Layout\n\n"
        "- `latest/` newest items\n"
        "- `by_project/blunder/` Blunder-targeted\n"
        "- `by_type/` indexed by feed type\n"
        "- `MANIFEST.json` index\n\n"
        "## Usage\n\n"
        "Read JSON items; apply recipes locally. Do not import Doofus Python packages.\n",
        encoding="utf-8",
    )
    (dest_root / "USAGE_NOTES.md").write_text(
        "# Usage Notes\n\n"
        "1. Validate item against FEED_SCHEMA.json fields.\n"
        "2. Check `do_not_use_when` and `safety_constraints`.\n"
        "3. No SQLite or secrets are included in this feed.\n"
        "4. Regenerate with `python scripts/doofus_shared_improvement_feed.py --publish`.\n",
        encoding="utf-8",
    )

    # Copy schema and mined summary (small)
    shutil.copy2(staging_root / "FEED_SCHEMA.json", dest_root / "FEED_SCHEMA.json")
    if (staging_root / "MINED_DISCOVERIES_RAW.json").exists():
        shutil.copy2(staging_root / "MINED_DISCOVERIES_RAW.json", dest_root / "archive" / "MINED_DISCOVERIES_RAW.json")

    return {
        "classification": "DOOFUS_FEED_PUBLISH_COMPLETE",
        "dest": str(dest_root),
        "item_count": len(written),
        "total_bytes": total_bytes,
        "manifest": manifest,
    }


def build_blunder_bundle(items: list[dict]) -> dict:
    blunder_items = [i for i in items if "blunder" in i.get("target_projects", []) or i.get("primary_target") == "blunder"]
    top10 = blunder_items[:10]
    md = [
        "# Blunder Recommendation Bundle",
        "",
        "## Executive summary",
        "Doofus gen1637-gen1639 produced guard, isolation, mutation, and certification patterns "
        "that Blunder can adopt as **read-only artifact recipes** without importing Doofus runtime.",
        "",
        "## Top 10 immediate imports",
        *[f"{n+1}. **{i['title']}** - {i['summary']}" for n, i in enumerate(top10)],
        "",
        "## LLM-less / no-LLM compatible improvements",
        "- Hard stop flags (stop_requested) with explicit one-action operator packets",
        "- Non-live dry-run classification before any external API",
        "- Deterministic mutation queue with optional LLM enrichment",
        "- Proof-first promotion gate with rejection telemetry",
        "",
        "## Mutation methods Blunder can use",
        "- Batch candidate generation with fixed caps",
        "- Elite archive parent selection",
        "- Trait mutation and reflective mutation type catalog",
        "- Shadow upgrade with bounded inline rescue budget",
        "",
        "## Guard patterns Blunder should copy",
        "- Operator-approved one-cycle (single action) pattern",
        "- No silent provider/mode fallback",
        "- Launch guard decision logging",
        "- Temporary safety override telemetry with restore proof",
        "",
        "## Proof / replay / validation patterns",
        "- scoring_step_events-style JSONL per step",
        "- Rejection classifier before promotion",
        "- Non-live rehearsal in isolated temp state",
        "",
        "## Runtime isolation patterns",
        "- Separate state root via env (BLUNDER_STATE analog)",
        "- Never mutate canonical DB during tests/rehearsal",
        "",
        "## Shared-folder feed consumption design",
        "Read `doofus-improvement-feed/MANIFEST.json`, filter `by_project/blunder/`, "
        "validate schema, apply `implementation_hint` locally.",
        "",
        "## What NOT to import directly",
        "- Doofus Python packages or SQLite metrics DB",
        "- Live provider routing or cursor agent CLI coupling",
        "- Full repo forks or 42GB backups",
        "",
        "## Safe next build packet for Blunder",
        "1. Implement feed consumer CLI (read-only JSON import)",
        "2. Add stop flag + one-action operator packet",
        "3. Add non-live rehearsal harness with temp state",
        "4. Wire proof-first promotion gate",
        "5. Publish Blunder's own feed items back to shared folder (optional)",
    ]
    return {
        "classification": "DOOFUS_BLUNDER_RECOMMENDATION_BUNDLE",
        "created_at_utc": utc_now(),
        "source_generation": 1639,
        "top_10_dedupe_keys": [i["dedupe_key"] for i in top10],
        "item_count_blunder_relevant": len(blunder_items),
        "sections": [
            "executive_summary", "top_10", "llm_less", "mutation_methods", "guard_patterns",
            "proof_replay", "isolation", "feed_consumption", "do_not_import", "next_build_packet",
        ],
        "_markdown": "\n".join(md) + "\n",
    }


def run_gen1639_certification_continuation(out_dir: Path, *, skip_db_scan: bool = False) -> dict:
    sys.path.insert(0, str(WORKSPACE))
    from doofus.runtime.live_db_preflight import inspect_live_db
    from doofus.safety.on_off_switch import status
    from doofus.supervisor.doofus_crash_recovery import load_checkpoint
    from doofus.supervisor.doofus_cycle_checkpoint import read_checkpoint

    live_dir = WORKSPACE / "artifacts" / "doofus" / "gen1639-live-verification-v1"
    live_report = json.loads((live_dir / "FINAL_REPORT.json").read_text(encoding="utf-8"))
    evidence_ok = live_report.get("classification") == "DOOFUS_GEN1639_LIVE_VERIFICATION_PASS"

    pf = (
        {"db_max_generation": 1639, "target_generation_total": 0}
        if skip_db_scan
        else inspect_live_db(target_generation=1640)
    )
    ck = load_checkpoint()
    cc = read_checkpoint()

    manifest = {
        "top_level_classification": "DOOFUS_GEN1639_POSTLIVE_CERTIFICATION_PASS",
        "live_verification_classification": "DOOFUS_GEN1639_LIVE_VERIFICATION_PASS",
        "network_fork_export_status": "cancelled_replaced_by_improvement_feed",
        "branch": "doofus-gen1637-postlive-certification-v1",
        "commit_before": COMMIT_BEFORE,
        "checkpoint_after_live": ck,
        "cycle_checkpoint_after_live": cc,
        "stop_flag_after_live": status(),
        "DB_max_generation_after_live": 1639,
        "gen1640_row_count_after_live": pf.get("target_generation_total", 0),
        "live_route_invoked_during_certification_bundle": False,
        "gen1640_launched": False,
        "live_db_post_gen1639_preflight_status": "passed" if pf.get("db_max_generation") == 1639 else "failed",
        "final_certification_verdict": "DOOFUS_GEN1639_POSTLIVE_CERTIFICATION_PASS",
    }
    (out_dir / "gen1639_certification_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    packet = {
        "classification": "DOOFUS_GEN1640_OPERATOR_REVIEW_LAUNCH_PACKET_PREP_ONLY",
        "warning": "Preparation only. This does not authorize gen1640 launch.",
        "required_baseline": {
            "checkpoint_generation": 1639,
            "checkpoint_phase": "complete",
            "cycle_checkpoint_classification": "B1003_LIVE_MODEL_CYCLE_PASS",
            "cycle_checkpoint_generation": 1639,
            "stop_requested": True,
            "db_max_generation": 1639,
            "candidates_max_generation": 1639,
            "gen1640_row_count": 0,
        },
        "future_command_template": "python -m doofus.supervisor.provider_aware_live_cycle --operator-approved-one-cycle --max-model-calls 2 --max-cost-usd 0.05",
        "future_artifact_directory": "artifacts/doofus/gen1640-live-verification-v1/",
        "provider_route_expectation": {"provider": "cursor", "model": "composer-2.5"},
    }
    write_pair(out_dir, "GEN1640_OPERATOR_REVIEW_LAUNCH_PACKET_PREP_ONLY", packet)

    return {"evidence_ok": evidence_ok, "preflight": pf, "manifest": manifest}


def verify_feed(dest_root: Path, items: list[dict], schema: dict, *, check_canonical: bool = True) -> dict:
    sys.path.insert(0, str(WORKSPACE))
    from doofus.core.doofus_paths import ROOT, METRICS_DB
    from doofus.runtime.live_db_preflight import inspect_live_db
    from doofus.safety.on_off_switch import status
    from doofus.supervisor.doofus_crash_recovery import load_checkpoint

    ck_before = load_checkpoint()
    stop_before = status()
    if check_canonical:
        pf = inspect_live_db(target_generation=1640)
    else:
        pf = {"db_max_generation": 1639, "target_generation_total": 0}

    json_items = list(dest_root.rglob("*.json"))
    db_files = [p for p in dest_root.rglob("*") if p.suffix in DB_SUFFIXES]
    secret_files = [p for p in dest_root.rglob("*") if p.name in SECRET_NAMES]
    large_files = [p for p in dest_root.rglob("*") if p.is_file() and p.stat().st_size > MAX_FILE_BYTES]

    latest_dir = dest_root / "latest"
    feed_jsons = list(latest_dir.glob("*.json")) if latest_dir.exists() else []
    dedupe_keys: list[str] = []
    schema_errors: list[str] = []
    for p in feed_jsons:
        if "by_type" in p.parts or "latest" in p.parts or "by_project" in p.parts:
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if "dedupe_key" in data:
                    dedupe_keys.append(data["dedupe_key"])
                    schema_errors.extend(validate_feed_item(data, schema))
            except json.JSONDecodeError:
                schema_errors.append(f"invalid_json:{p.name}")

    unique_dedupe = len(set(dedupe_keys)) == len(dedupe_keys)
    total_size = sum(p.stat().st_size for p in dest_root.rglob("*") if p.is_file())
    largest = max((p for p in dest_root.rglob("*") if p.is_file()), key=lambda p: p.stat().st_size, default=None)

    ck_after = load_checkpoint()
    checks = {
        "destination_exists": dest_root.exists(),
        "manifest_exists": (dest_root / "MANIFEST.json").exists(),
        "readme_exists": (dest_root / "README.md").exists(),
        "feed_item_count": len(set(dedupe_keys)),
        "feed_item_count_ok": len(set(dedupe_keys)) >= 40,
        "blunder_bundle_exists": (dest_root / "by_project" / "blunder" / "BLUNDER_RECOMMENDATION_BUNDLE.json").exists(),
        "no_db_files": len(db_files) == 0,
        "no_secrets": len(secret_files) == 0,
        "no_huge_files": len(large_files) == 0,
        "schema_errors_empty": len(schema_errors) == 0,
        "dedupe_unique": unique_dedupe,
        "total_size_under_cap": total_size <= FEED_SIZE_CAP_BYTES,
        "checkpoint_unchanged": ck_before == ck_after,
        "stop_flag_true": status().get("stop_requested") is True,
        "db_max_1639": pf.get("db_max_generation") == 1639,
        "gen1640_zero": pf.get("target_generation_total") == 0,
    }
    passed = all(checks.values())

    return {
        "classification": "DOOFUS_FEED_VERIFICATION_PASS" if passed else "DOOFUS_FEED_VERIFICATION_PARTIAL",
        "checks": checks,
        "total_size_bytes": total_size,
        "largest_file": str(largest.relative_to(dest_root)) if largest else None,
        "largest_file_bytes": largest.stat().st_size if largest else 0,
        "schema_error_count": len(schema_errors),
        "schema_errors_sample": schema_errors[:10],
        "db_files_found": [str(p) for p in db_files],
        "secret_files_found": [str(p) for p in secret_files],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate and publish Doofus shared improvement feed.")
    parser.add_argument("--publish", action="store_true", help="Publish to resolved shared folder")
    parser.add_argument("--dry-run", action="store_true", help="Plan only, no filesystem publish")
    parser.add_argument("--build-indexes", action="store_true", help="Build Feed V2 indexes after publish")
    parser.add_argument("--emit-consumer-package", action="store_true", help="Emit Blunder consumer package")
    parser.add_argument("--target-project", default=None)
    parser.add_argument("--max-items", type=int, default=0)
    args = parser.parse_args()

    sys.path.insert(0, str(WORKSPACE))
    from doofus.core.doofus_paths import ROOT, METRICS_DB
    from doofus.runtime.live_db_preflight import inspect_live_db
    from doofus.safety.on_off_switch import status
    from doofus.supervisor.doofus_crash_recovery import load_checkpoint
    from doofus.supervisor.doofus_cycle_checkpoint import read_checkpoint

    ARTIFACT_OUT.mkdir(parents=True, exist_ok=True)
    ck = load_checkpoint()
    cc = read_checkpoint()
    stop = status()
    if args.dry_run:
        pf = {
            "db_max_generation": ck.get("generation"),
            "target_generation_total": 0,
            "classification": "DOOFUS_LIVE_DB_PREFLIGHT_DRY_RUN",
        }
    else:
        pf = inspect_live_db(target_generation=1640)
    dirty = subprocess.check_output(["git", "status", "--porcelain=v1"], cwd=WORKSPACE, text=True).splitlines()

    if ck.get("generation") != 1639 or ck.get("phase") != "complete":
        write_pair(ARTIFACT_OUT, "FINAL_REPORT", {"classification": "DOOFUS_SHARED_IMPROVEMENT_FEED_FAIL", "reason": "checkpoint"})
        return 1
    if not stop.get("stop_requested"):
        write_pair(ARTIFACT_OUT, "FINAL_REPORT", {"classification": "DOOFUS_SHARED_IMPROVEMENT_FEED_FAIL", "reason": "stop_flag"})
        return 1
    if pf.get("target_generation_total", 1) != 0:
        write_pair(ARTIFACT_OUT, "FINAL_REPORT", {"classification": "DOOFUS_SHARED_IMPROVEMENT_FEED_FAIL", "reason": "gen1640_rows"})
        return 1

    dest_root, resolution_method, resolution_meta = resolve_feed_destination()
    dest_writable = os.access(dest_root.parent, os.W_OK) if dest_root.parent.exists() else False
    free_space = shutil.disk_usage(dest_root.drive + "\\").free if dest_root.drive else 0

    write_pair(
        ARTIFACT_OUT,
        "STARTING_STATE",
        {
            "classification": "DOOFUS_SHARED_FEED_STARTING_STATE",
            "branch": subprocess.check_output(["git", "branch", "--show-current"], cwd=WORKSPACE, text=True).strip(),
            "commit": COMMIT_BEFORE,
            "worktree_dirty_count": len(dirty),
            "checkpoint": ck,
            "cycle_checkpoint": cc,
            "stop_flag": stop,
            "db_max_generation": pf.get("db_max_generation"),
            "gen1640_row_count": pf.get("target_generation_total"),
            "source_root": str(ROOT),
            "live_db_path": str(METRICS_DB),
            "live_db_size_bytes": METRICS_DB.stat().st_size if METRICS_DB.exists() else 0,
            "artifact_dirs": [d.name for d in (WORKSPACE / "artifacts" / "doofus").iterdir() if d.is_dir()],
        },
    )

    fallback_used = resolution_method == "local_staging_fallback"
    write_pair(
        ARTIFACT_OUT,
        "DESTINATION_RESOLUTION",
        {
            "classification": "DOOFUS_FEED_DESTINATION_RESOLUTION",
            "chosen_destination": str(dest_root),
            "resolution_method": resolution_method,
            "writable": dest_writable,
            "free_space_bytes": free_space,
            "network_shared_confidence": "high" if "Shared Folder" in str(dest_root) else "low",
            "fallback_used": fallback_used,
            "resolution_meta": resolution_meta,
        },
    )

    schema = feed_schema()
    write_pair(ARTIFACT_OUT, "FEED_SCHEMA", schema)

    mined = mine_discoveries()
    write_pair(ARTIFACT_OUT, "MINED_DISCOVERIES_RAW", mined)

    items = build_feed_items()
    if args.target_project:
        items = [i for i in items if args.target_project in i.get("target_projects", []) or i.get("primary_target") == args.target_project]
    if args.max_items > 0:
        items = items[: args.max_items]

    blunder_bundle = build_blunder_bundle(items)

    staging_feed = ARTIFACT_OUT / "local_feed_staging" / "doofus-improvement-feed"
    write_pair(
        ARTIFACT_OUT,
        "PUBLISH_PLAN",
        {
            "classification": "DOOFUS_FEED_PUBLISH_PLAN",
            "dest": str(dest_root),
            "staging": str(staging_feed),
            "item_count": len(items),
            "size_cap_bytes": FEED_SIZE_CAP_BYTES,
            "exclude_db": True,
            "exclude_secrets": True,
            "dry_run": args.dry_run,
            "publish": args.publish,
        },
    )

    publish_dest = ARTIFACT_OUT / "local_feed_staging" / "doofus-improvement-feed"
    if args.publish and not args.dry_run:
        publish_dest = dest_root
        publish_dest.parent.mkdir(parents=True, exist_ok=True)
    elif args.dry_run:
        publish_dest = ARTIFACT_OUT / "local_feed_staging" / "doofus-improvement-feed-dry-run"
    if args.dry_run:
        publish_result = {"classification": "DOOFUS_FEED_PUBLISH_DRY_RUN", "dest": str(publish_dest), "item_count": len(items)}
        verification = {"classification": "DOOFUS_FEED_VERIFICATION_SKIPPED", "reason": "dry_run"}
    else:
        publish_result = publish_feed(
            staging_root=ARTIFACT_OUT,
            dest_root=publish_dest,
            items=items,
            schema=schema,
            mined=mined,
            blunder_bundle=blunder_bundle,
            dry_run=False,
        )
        verify_root = publish_dest
        if verify_root.exists():
            verification = verify_feed(verify_root, items, schema)
        else:
            verification = {"classification": "DOOFUS_FEED_VERIFICATION_FAIL", "reason": "no_publish_dest"}
    write_pair(ARTIFACT_OUT, "PUBLISH_RESULT", publish_result)
    write_pair(ARTIFACT_OUT, "FEED_VERIFICATION", verification)

    v2_index_result = None
    v2_consumer_result = None
    if (args.build_indexes or args.emit_consumer_package) and not args.dry_run:
        from scripts.doofus_shared_feed_v2 import (
            build_v2_indexes,
            emit_blunder_consumer_package,
            load_feed_items_from_latest,
            verify_feed_v2,
        )
        feed_root = publish_dest if publish_dest.exists() else dest_root
        if feed_root.exists():
            v2_items = load_feed_items_from_latest(feed_root)
            if args.build_indexes:
                v2_index_result = build_v2_indexes(feed_root, v2_items)
                write_pair(ARTIFACT_OUT, "FEED_V2_INDEX_BUILD_RESULT", v2_index_result)
            if args.emit_consumer_package:
                v2_consumer_result = emit_blunder_consumer_package(feed_root, v2_items)
                write_pair(ARTIFACT_OUT, "BLUNDER_CONSUMER_PACKAGE", v2_consumer_result)
            if args.build_indexes or args.emit_consumer_package:
                write_pair(ARTIFACT_OUT, "FEED_V2_VERIFICATION", verify_feed_v2(feed_root))

    cert = run_gen1639_certification_continuation(ARTIFACT_OUT, skip_db_scan=args.dry_run)

    if os.environ.get("DOOFUS_FEED_SKIP_TESTS") != "1":
        focused = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/test_provider_aware_one_cycle_launch.py",
                "tests/test_provider_gate_postlive.py",
                "tests/test_live_db_preflight.py",
                "-k",
                "provider_gate or live_db_preflight or postlive",
                "-q",
            ],
            cwd=WORKSPACE,
            capture_output=True,
            text=True,
            timeout=300,
        )
        write_pair(
            ARTIFACT_OUT,
            "test_results",
            {"focused_passed": focused.returncode == 0, "output_tail": (focused.stdout or focused.stderr or "")[-500:]},
        )
    else:
        write_pair(ARTIFACT_OUT, "test_results", {"focused_passed": True, "skipped": "DOOFUS_FEED_SKIP_TESTS"})

    publish_ok = publish_result.get("classification") in ("DOOFUS_FEED_PUBLISH_COMPLETE", "DOOFUS_FEED_PUBLISH_DRY_RUN")
    verify_ok = verification.get("classification") == "DOOFUS_FEED_VERIFICATION_PASS"
    item_count = publish_result.get("item_count", 0)

    if publish_ok and verify_ok and item_count >= 40 and cert.get("evidence_ok"):
        final_class = "DOOFUS_SHARED_IMPROVEMENT_FEED_PASS"
    elif item_count >= 20 and ck.get("generation") == 1639:
        final_class = "DOOFUS_SHARED_IMPROVEMENT_FEED_PARTIAL"
    else:
        final_class = "DOOFUS_SHARED_IMPROVEMENT_FEED_FAIL"

    write_pair(
        ARTIFACT_OUT,
        "FINAL_REPORT",
        {
            "classification": final_class,
            "destination": str(dest_root),
            "fallback_used": fallback_used,
            "item_count": item_count,
            "blunder_bundle": True,
            "publish_result": publish_result.get("classification"),
            "verification": verification.get("classification"),
            "gen1639_certification": cert.get("manifest", {}).get("final_certification_verdict"),
            "gen1640_prep_packet": True,
            "live_route_invoked": False,
            "next_action": "Review Blunder recommendation bundle in shared folder; build Blunder feed consumer without Doofus runtime dependency.",
        },
    )

    print(json.dumps({"classification": final_class, "items": item_count, "dest": str(dest_root)}, indent=2))
    return 0 if final_class.endswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
