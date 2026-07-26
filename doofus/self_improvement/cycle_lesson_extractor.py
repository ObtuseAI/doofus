"""Extract Doofus-native lessons from gen1637-gen1639 artifact bundles."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from doofus.self_improvement.improvement_item import ImprovementItem

ARTIFACT_ROOTS = [
    "gen1637-postlive-certification-v1",
    "gen1638-launch-guard-fix-v1",
    "gen1638-db-scrub-readiness-v1",
    "gen1638-live-verification-v2",
    "gen1638-postlive-certification-v1",
    "gen1639-live-verification-v1",
    "shared-improvement-feed-v1",
    "shared-improvement-feed-v2-blunder-consumer-v1",
]

KEYWORD_TYPE_MAP = {
    "proof_builder": "proof_builder_improvement",
    "proof-builder": "proof_builder_improvement",
    "inline_rescue": "proof_builder_improvement",
    "inline rescue": "proof_builder_improvement",
    "mutation": "mutation_method",
    "map_elites": "mutation_method",
    "map-elites": "mutation_method",
    "guard": "guard_pattern",
    "provider_gate": "guard_pattern",
    "stop_flag": "guard_pattern",
    "preflight": "guard_pattern",
    "telemetry": "telemetry_improvement",
    "scoring": "scoring_improvement",
    "repair": "repair_recipe",
    "scrub": "repair_recipe",
    "cycle": "cycle_quality_improvement",
    "candidate": "cycle_quality_improvement",
    "feed": "artifact_feed_improvement",
    "isolated": "runtime_isolation_improvement",
    "operator": "operator_packet_improvement",
}


def _infer_type(text: str) -> str:
    lower = text.lower()
    for key, type_ in KEYWORD_TYPE_MAP.items():
        if key in lower:
            return type_
    return "cycle_quality_improvement"


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:48]


def _mine_json_file(path: Path, rel: str, generation: int) -> list[ImprovementItem]:
    items: list[ImprovementItem] = []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return items

    def add_from_fields(title: str, summary: str, problem: str = "", recommendation: str = "") -> None:
        if not title or len(title) < 8:
            return
        type_ = _infer_type(f"{path.name} {title} {summary}")
        items.append(
            ImprovementItem.create(
                type_=type_,
                title=title[:120],
                summary=summary[:400] or title,
                problem=problem[:300] or summary[:200],
                recommendation=recommendation[:300] or summary[:200],
                source_generation=generation,
                source_artifacts=[rel],
                validation_method="artifact_review_and_targeted_test",
            )
        )

    if isinstance(data, dict):
        classification = str(data.get("classification", ""))
        if classification and "PASS" in classification.upper():
            add_from_fields(
                f"Lesson from {path.stem}: {classification}",
                f"Artifact {rel} recorded {classification}.",
                recommendation=f"Review {rel} before next cycle.",
            )
        for key in ("next_action", "recommendation", "root_cause", "fix_summary", "reason"):
            val = data.get(key)
            if isinstance(val, str) and len(val) > 20:
                add_from_fields(f"{path.stem}: {key}", val, recommendation=val)
        findings = data.get("findings") or data.get("checks") or data.get("blockers")
        if isinstance(findings, dict):
            for fk, fv in findings.items():
                if isinstance(fv, (str, bool)) and fv:
                    add_from_fields(f"{path.stem}: {fk}", str(fv))
        elif isinstance(findings, list):
            for entry in findings[:5]:
                if isinstance(entry, str):
                    add_from_fields(f"{path.stem} finding", entry)
    return items


def _seeded_doofus_lessons(generation: int) -> list[ImprovementItem]:
    """Hand-curated Doofus-native lessons from gen1637-gen1639 cycles."""
    seeds: list[tuple[str, str, str, str, str, list[str]]] = [
        ("mutation_method", "Candidate batch size 24 with zero-promotion telemetry", "Track promoted vs rejected per cycle.", "24 candidates generated; 0 promoted when proof gate fails.", "Log rejection_classifier per candidate.", ["mutation", "scoring"]),
        ("mutation_method", "MAP-Elites insertion discipline", "Prevent archive corruption on concurrent writes.", "SQLite lock errors during MAP-Elites active connection.", "Use lock-wait with bounded timeout on active connection.", ["map_elites", "mutation"]),
        ("mutation_method", "Shadow upgrade bounded inline rescue", "Cap shadow_upgrade work inside rescue budget.", "shadow_upgrade consumes rescue deadline.", "Reserve deadline slice; skip proof_builder when remaining < 1s.", ["inline_rescue", "proof_builder"]),
        ("mutation_method", "Trait mutation from elite archive", "Reuse elite traits for deterministic variants.", "Random mutations lack lineage.", "Pull parent traits from elite_archive with dedupe.", ["mutation", "elite_archive"]),
        ("mutation_method", "GEPA reflective mutation type", "Track reflective mutation outcomes separately.", "Mixed mutation types obscure failure modes.", "Tag mutation_type=gepa_reflective in telemetry.", ["mutation"]),
        ("mutation_method", "Deterministic dry-run proposal fill", "Non-live cycles need synthetic proposals.", "Empty proposal list skips mutation path.", "DOOFUS_FORCE_MODEL_DRY_RUN fills capped synthetic proposals.", ["mutation", "dry_run"]),
        ("mutation_method", "Candidate generation identity guard", "candidate_id must encode generation.", "Orphan rows from generation mismatch.", "Assert generation in candidate_id prefix at insert.", ["mutation", "candidates"]),
        ("mutation_method", "Mutation lineage tracking JSONL", "Record parent_id chain per mutation.", "Cannot replay mutation decisions.", "Append mutation_lineage.jsonl per batch.", ["mutation", "telemetry"]),
        ("mutation_method", "Mutation operator scoring by validator outcome", "Weight operators by promotion rate.", "All operators treated equally.", "Score operators from historical validator pass rate.", ["mutation", "scoring"]),
        ("mutation_method", "Mutation failure memory per trait", "Avoid repeating failed trait combos.", "Same failing traits re-mutated.", "Maintain trait_failure_counts in STATE.", ["mutation"]),
        ("mutation_method", "High-score enqueue every 5th generation", "Periodic proof queue mining.", "Under-proven high scores never enqueued.", "select_and_enqueue when generation % 5 == 0.", ["proof_builder", "mutation"]),
        ("mutation_method", "Shadow elite retest limit 10", "Bound retest work in inline rescue.", "Unbounded retest stalls cycle.", "retest_shadow_elites(limit=10).", ["inline_rescue"]),
        ("mutation_method", "Compound evolution acceleration hook", "Optional compounding after cycle.", "Missed compounding opportunities.", "after_compounding_cycle with stop guard.", ["evolution"]),
        ("mutation_method", "Adaptive mutation pressure tuning", "Adjust pressure from rejection rate.", "Fixed pressure ignores cycle feedback.", "Read rejection rate; tune pressure config.", ["mutation", "evolution"]),
        ("mutation_method", "Model proposal applier validation gate", "Validate proposals before apply.", "Invalid proposals corrupt candidates.", "Schema-check proposals; reject malformed.", ["mutation", "model_router"]),
        ("proof_builder_improvement", "Proof-builder generation identity guard", "Queue entry generation must match candidate.", "generation_mismatch blocks proof.", "Compare queued_generation vs candidate.generation in process_one.", ["proof_builder"]),
        ("proof_builder_improvement", "Proof-builder child process timeout", "Isolate proof build in subprocess.", "In-process proof hangs supervisor.", "DOOFUS_PROOF_BUILDER_ITEM_TIMEOUT_SECONDS with record_child_timeout.", ["proof_builder"]),
        ("proof_builder_improvement", "Proof skip reason telemetry", "Record why proof was skipped.", "Silent skips hide backlog.", "Log enqueue_skipped and proof_blocked outcomes.", ["proof_builder", "telemetry"]),
        ("proof_builder_improvement", "Proof-builder deadline reserve", "Skip proof batch when rescue budget exhausted.", "proof_builder runs past inline rescue deadline.", "Skip when remaining_seconds <= 1.0.", ["proof_builder", "inline_rescue"]),
        ("proof_builder_improvement", "Queued-for-proof-builder count digest", "Surface pending queue size each cycle.", "Queue visibility poor.", "queue_summary in inline_rescue end event.", ["proof_builder"]),
        ("proof_builder_improvement", "Proof-builder replay harness", "Replay proof artifacts for regression.", "No replay path for proof failures.", "build_replay_proof in isolated test DB.", ["proof_builder", "tests"]),
        ("proof_builder_improvement", "Proof partial outcome retry cap", "Cap retries for proof_partial.", "Infinite retry loops.", "DOOFUS_PROOF_BUILDER_MAX_RETRIES.", ["proof_builder"]),
        ("proof_builder_improvement", "Promotion gate after proof success", "Only promote after evaluate_promotion pass.", "Promotion without proof.", "evaluate_promotion after build_proof_artifacts.", ["proof_builder", "promotion"]),
        ("proof_builder_improvement", "Shadow elite proof_builder arena tag", "Tag arena=shadow_elite_proof_builder.", "Mixed arena conflates metrics.", "Insert arena_results with distinct tag.", ["proof_builder"]),
        ("proof_builder_improvement", "Proof-builder batch slowest item tracking", "Track slowest_item_id per batch.", "Cannot identify proof bottleneck.", "run_proof_builder_batch max_item_duration_ms.", ["proof_builder", "telemetry"]),
        ("telemetry_improvement", "Unified cycle ledger JSONL", "Single ledger for cycle phases.", "Telemetry scattered across files.", "cycle_ledger.jsonl with stage+duration.", ["telemetry"]),
        ("telemetry_improvement", "Compact generation summary builder", "One JSON/MD summary per generation.", "Operators parse many artifacts.", "doofus_generation_summary.py --generation N.", ["telemetry", "reporting"]),
        ("telemetry_improvement", "Guard-decision digest", "Aggregate stop/provider/preflight decisions.", "Guard outcomes hard to audit.", "guard_decision_digest.json per bundle.", ["telemetry", "guard"]),
        ("telemetry_improvement", "Scoring bottleneck digest", "Slowest scoring substeps per generation.", "scoring_step_events hard to summarize.", "Aggregate max duration_ms by substep.", ["scoring", "telemetry"]),
        ("telemetry_improvement", "Live/non-live route event unification", "Normalize model_call_events classification.", "Mixed dry-run/live labels.", "Standardize classification field values.", ["model_router", "telemetry"]),
        ("telemetry_improvement", "DB preflight event normalization", "Log preflight as structured events.", "Preflight only in bundle artifacts.", "Emit preflight_event on each check-only run.", ["live_db", "telemetry"]),
        ("telemetry_improvement", "Inline rescue per-stage duration summary", "Summarize stage elapsed from events.", "Only raw jsonl available.", "Parse inline_rescue_events for stage totals.", ["inline_rescue"]),
        ("telemetry_improvement", "Supervisor phase watchdog telemetry", "Record phase stalls.", "Hung phases undetected.", "supervisor_phase_watchdog events.", ["supervisor"]),
        ("telemetry_improvement", "Pipeline warn aggregation", "Count pipeline_warn by component.", "Warnings lost in logs.", "Aggregate pipeline_warn JSONL.", ["telemetry"]),
        ("telemetry_improvement", "Model call ledger compact export", "Export model calls per generation.", "Full ledger too large for reports.", "Generation-filtered model_call summary.", ["model_router"]),
        ("guard_pattern", "Provider gate no silent fallback", "Live route requires explicit readiness.", "Hidden dry-run during live cycle.", "Separate may_call_live_provider from one-cycle check.", ["provider_gate"]),
        ("guard_pattern", "One-cycle approval token semantics", "operator-approved-one-cycle flag scope.", "Stop flag blocks authorized single cycle.", "try/finally stop clear with telemetry.", ["launch_guard"]),
        ("guard_pattern", "Stop flag restoration proof", "Verify stop_requested after one-cycle.", "Stop left cleared after cycle.", "Post-cycle assert stop_requested=true.", ["stop_flag"]),
        ("guard_pattern", "Target-generation contamination check", "Preflight target_generation+1 rows.", "Future gen rows before launch.", "inspect_live_db(target_generation=N+1).", ["live_db_preflight"]),
        ("guard_pattern", "Non-live dry-run boundary proof", "Non-live must be DOOFUS_MODEL_DRY_RUN.", "Accidental provider calls.", "verify_nonlive_dry_run_guard probe.", ["dry_run"]),
        ("guard_pattern", "Process singleton launch guard", "Prevent duplicate supervisors.", "Double supervisor corrupts state.", "process_singleton lock before cycle.", ["supervisor"]),
        ("guard_pattern", "Budget guard max cost cap", "Enforce max-cost-usd per cycle.", "Runaway provider spend.", "budget_guard before model calls.", ["budget"]),
        ("guard_pattern", "Emergency stop precedence", "EMERGENCY_STOP overrides run_enabled.", "Partial stop states.", "Check EMERGENCY_STOP before may_run.", ["stop_flag"]),
        ("guard_pattern", "Generation checkpoint phase gate", "phase=complete required before next gen.", "Launch mid-phase.", "load_checkpoint phase check in launch packet.", ["checkpoint"]),
        ("guard_pattern", "Dirty launch-critical source refusal", "Block launch if routing/scoring dirty.", "Unreviewed changes in launch path.", "Launch packet refusal matrix.", ["operator"]),
        ("repair_recipe", "Backup-first DB scrub recipe", "Copy DB before any scrub.", "Scrub without rollback path.", "doofus_metrics backup then scrub above checkpoint.", ["live_db"]),
        ("repair_recipe", "Provider gate stop preblock fix", "Fix stop_requested preblock mismatch.", "One-cycle blocked incorrectly.", "Clear stop inside guarded try/finally only.", ["launch_guard"]),
        ("repair_recipe", "MAP-Elites active connection lock wait", "Wait on SQLite lock with timeout.", "database is locked errors.", "timeout=5.0 on connect; retry loop.", ["map_elites"]),
        ("repair_recipe", "Orphan generation row scrub", "Remove rows above checkpoint generation.", "Contamination from partial cycles.", "Scrub candidates/cycles above checkpoint.", ["live_db"]),
        ("repair_recipe", "Inline rescue timeout containment", "Classify timeout as nonfatal.", "Timeout aborts entire cycle.", "INLINE_RESCUE_TIMEOUT classification.", ["inline_rescue"]),
        ("repair_recipe", "PowerShell UTF-8 BOM log decode", "Decode logs with BOM handling.", "Garbled log parsing on Windows.", "utf-8-sig when reading ps logs.", ["runtime"]),
        ("repair_recipe", "Checkpoint restore from cycle_checkpoint", "Align checkpoint with cycle pass.", "Checkpoint/cycle mismatch.", "Restore from B1003 pass snapshot.", ["checkpoint"]),
        ("repair_recipe", "Proof queue stale entry purge", "Remove entries for missing candidates.", "Ghost queue entries.", "Purge not_found outcomes periodically.", ["proof_builder"]),
        ("repair_recipe", "Runtime heal session cleanup", "Clean stale sessions before cycle.", "Orphan sessions block progress.", "session_cleanup before prepare_cycle.", ["runtime"]),
        ("repair_recipe", "Metrics writer connection retry", "Retry DB writes on transient lock.", "Write failures during scoring.", "Bounded retry on metrics_writer.", ["metrics"]),
        ("cycle_quality_improvement", "Rejection classifier telemetry", "Classify why each candidate rejected.", "Opaque rejection reasons.", "rejection_reason field + classifier tag.", ["scoring"]),
        ("cycle_quality_improvement", "Scorecard reuse across generations", "Reuse score components where valid.", "Redundant scoring work.", "Cache scorecard by trait hash.", ["scoring"]),
        ("cycle_quality_improvement", "Generation-to-generation lesson carryover", "Feed prior cycle lessons to catalog.", "Lessons lost between gens.", "self_improvement catalog ingest.", ["self_improvement"]),
        ("cycle_quality_improvement", "Candidate-to-proof handoff visibility", "Track enqueue-to-proof latency.", "Handoff delays invisible.", "Timestamp enqueue and proof start.", ["proof_builder"]),
        ("cycle_quality_improvement", "Best-ever ledger cross-check", "Validate ledger vs DB max score.", "Ledger drift from DB.", "Periodic best_ever_ledger reconcile.", ["evolution"]),
        ("artifact_feed_improvement", "Doofus self-consumable improvement feed", "Doofus reads own feed for seeds.", "Feed only exported externally.", "self_improvement catalog from feed items.", ["feed"]),
        ("artifact_feed_improvement", "Dedupe and scoring of discoveries", "Stable dedupe_key on all items.", "Duplicate improvement ideas.", "SHA256 dedupe in catalog.", ["feed"]),
        ("artifact_feed_improvement", "Next-cycle candidate seed generation", "Seeds from catalog priority index.", "Manual seed selection only.", "next_cycle_seed_recommendations.json.", ["self_improvement"]),
        ("runtime_isolation_improvement", "Isolated runtime test pattern", "Copy runtime to temp for tests.", "Tests mutate canonical state.", "isolated_runtime_copy in tests.", ["tests"]),
        ("runtime_isolation_improvement", "Child process runtime path isolation", "DOOFUS_ROOT override in child.", "Child inherits wrong paths.", "Env override in subprocess proof build.", ["runtime"]),
        ("operator_packet_improvement", "Gen1640 prep-only launch packet", "Document baseline before gen1640.", "Launch without explicit baseline.", "GEN1640_OPERATOR_REVIEW_LAUNCH_PACKET_PREP_ONLY.", ["operator"]),
        ("operator_packet_improvement", "Refusal matrix in launch packets", "List all launch refusal conditions.", "Ambiguous launch criteria.", "Required refusal conditions in packet.", ["operator"]),
        ("scoring_improvement", "Per-candidate scoring timeout budget", "Cap scoring time per candidate.", "Slow candidate blocks batch.", "Timeout single candidate not cycle.", ["scoring"]),
        ("scoring_improvement", "Scoring step events JSONL", "Log each scoring substep duration.", "Cannot profile scoring.", "scoring_step_events.jsonl.", ["scoring"]),
    ]
    items: list[ImprovementItem] = []
    for type_, title, summary, problem, recommendation, subsystems in seeds:
        items.append(
            ImprovementItem.create(
                type_=type_,
                title=title,
                summary=summary,
                problem=problem,
                recommendation=recommendation,
                source_generation=generation,
                source_artifacts=["seeded:gen1637-gen1639-lessons"],
                affected_subsystems=subsystems,
                validation_method="targeted_pytest_and_nonlive_rehearsal",
                required_tests=[f"tests/test_{subsystems[0]}.py"] if subsystems else [],
            )
        )
    return items


def extract_lessons_from_artifacts(workspace: Path, generation: int = 1639) -> list[ImprovementItem]:
    items: list[ImprovementItem] = []
    items.extend(_seeded_doofus_lessons(generation))
    art_root = workspace / "artifacts" / "doofus"
    for bundle in ARTIFACT_ROOTS:
        bundle_path = art_root / bundle
        if not bundle_path.is_dir():
            continue
        for json_path in sorted(bundle_path.glob("*.json"))[:30]:
            rel = str(json_path.relative_to(workspace)).replace("\\", "/")
            items.extend(_mine_json_file(json_path, rel, generation))
    return items
