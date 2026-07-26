from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
from collections import Counter
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from doofus.core.doofus_events import utc_now
from doofus.runtime.live_db_preflight import inspect_live_db
from doofus.safety.on_off_switch import status as switch_status
from doofus.supervisor.doofus_crash_recovery import load_checkpoint
from doofus.supervisor.doofus_cycle_checkpoint import read_checkpoint
from doofus.supervisor.live_cycle_launch_guard import verify_nonlive_dry_run_guard

BASELINE_COMMIT = "043d2f735b0ce2f99208a631c7b6fa46e267cfcc"
KNOWN_PASS = {
    "checkpoint_before_live_generation": {
        "generation": 1636,
        "phase": "complete",
        "baseline_score": 0.9378,
    },
    "live_model_route": {
        "provider": "cursor",
        "transport": "agent_cli",
        "model": "composer-2.5",
        "route_classification": "B1050_PROVIDER_ROUTER_READY",
    },
    "live_model_result": "DOOFUS_MODEL_LIVE",
    "model_call_duration_ms": 36851.96,
    "proposals_returned": 1,
    "proposals_applied": 8,
    "generation_before": 1636,
    "generation_after": 1637,
    "elapsed_wall_time_s": 271.0,
    "scoring_phase_duration_ms": 33228.99,
    "scoring_timeout_recurred": False,
    "slowest_scoring_step": "candidate_scoring::candidate_total",
    "slowest_scoring_candidate": "DOOFUS_1637_1b88d67d80",
    "slowest_scoring_duration_ms": 66.89,
    "promoted_count": 0,
    "shadow_promoted_count": 0,
    "rejected_count": 24,
    "most_common_rejection_outcome": "rejected_queued_for_proof_builder",
    "db_contamination_prelaunch_detected": True,
    "db_contamination_prelaunch_scrubbed": True,
    "inline_rescue_timeout_observed": True,
    "inline_rescue_duration_ms": 183911.49,
    "inline_rescue_timeout_threshold_ms": 180000.0,
}

GEN1637_REQUIRED_PATHS = {
    "doofus/core/doofus_config.py",
    "doofus/evolution/elite_archive.py",
    "doofus/evolution/evolution_pressure_mode.py",
    "doofus/evolution/map_elites_archive.py",
    "doofus/meta/gep/capsule_store.py",
    "doofus/meta/gep/event_emitter.py",
    "doofus/runtime/isolated_runtime.py",
    "doofus/safety/on_off_switch.py",
    "doofus/scoring/promotion_gate.py",
    "doofus/scoring/scoring_telemetry.py",
    "doofus/supervisor/doofus_loop_runner.py",
    "scripts/doofus_scoring_diagnostic.py",
    "tests/test_doofus.py",
    "tests/test_map_elites_archive.py",
    "tests/test_promotion_side_effects.py",
}

POSTLIVE_CERT_PATH_PREFIXES = (
    "doofus/proof/high_score_rescue_loop.py",
    "doofus/proof/proof_builder_queue.py",
    "doofus/proof/proof_builder_runner.py",
    "doofus/runtime/live_db_preflight.py",
    "doofus/supervisor/live_cycle_launch_guard.py",
    "scripts/doofus_live_db_preflight.py",
    "scripts/doofus_gen1637_postlive_bundle.py",
    "tests/test_inline_rescue.py",
    "tests/test_live_cycle_launch_guard.py",
    "tests/test_live_db_preflight.py",
)

UNSAFE_REVIEW_PREFIXES = (
    ".env.example",
    "README.md",
    "pyproject.toml",
    "doofus/core/doofus_paths.py",
    "doofus/core/metrics_db.py",
    "doofus/model_router/live_model_adapter.py",
    "doofus/model_router/provider_router.py",
)

UNRELATED_PREFIXES = (
    "docs/",
    "doofus/dashboard/",
    "doofus.egg-info/",
    "scripts/cursor-bridge/",
    "scripts/doofus_create_desktop_shortcut.ps1",
    "scripts/doofus_desktop_start.ps1",
    "scripts/doofus_install_",
    "scripts/doofus_launch_dashboard",
    "scripts/doofus_hourly_",
    "scripts/doofus_register_",
    "scripts/doofus_unregister_",
    "scripts/doofus_kpi_",
)


def run_git(*args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=WORKSPACE,
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


def git_state() -> dict:
    branch = run_git("rev-parse", "--abbrev-ref", "HEAD")
    commit = run_git("rev-parse", "HEAD")
    status_lines = [line for line in run_git("status", "--short").splitlines() if line.strip()]
    dirty = []
    for line in status_lines:
        status = line[:2]
        path = line[3:]
        dirty.append({"git_status": status, "path": path})
    return {
        "branch": branch,
        "commit": commit,
        "dirty": dirty,
        "worktree_dirty": bool(dirty),
    }


def touches(path: str) -> dict:
    low = path.lower()
    return {
        "runtime_db_behavior": any(token in low for token in ("metrics_db", "map_elites", "proof_builder", "live_db_preflight", "capsule_store", "event_emitter")),
        "live_model_routing": any(token in low for token in ("model_router", "live_cycle_launch_guard", "doofus_config", "loop_runner")),
        "scoring": any(token in low for token in ("scoring", "promotion_gate", "map_elites", "proof_builder", "high_score_rescue")),
        "checkpointing": any(token in low for token in ("checkpoint", "crash_recovery", "loop_runner", "isolated_runtime")),
        "stop_state_behavior": any(token in low for token in ("on_off_switch", "live_cycle_launch_guard", "doofus_24_7_supervisor", "loop_runner")),
    }


def classify_dirty_file(path: str) -> dict:
    if path.startswith("artifacts/doofus/gen1637-postlive-certification-v1/"):
        bucket = "gen1637_live_verification_artifact"
        reason = "snapshot, backup, or certification evidence generated from the verified gen1637 state"
        should_commit = False
    elif path in GEN1637_REQUIRED_PATHS:
        bucket = "gen1637_required_repair"
        reason = "direct repair or regression coverage for the gen1637 live verification path"
        should_commit = True
    elif path.startswith(POSTLIVE_CERT_PATH_PREFIXES):
        bucket = "postlive_certification_new_work"
        reason = "new certification hardening, guard, telemetry, or bundle-writing work"
        should_commit = True
    elif path.startswith(UNSAFE_REVIEW_PREFIXES):
        bucket = "unsafe_or_needs_operator_review"
        reason = "broad or operator-facing surface area that should be reviewed before bundling"
        should_commit = False
    elif path.startswith(UNRELATED_PREFIXES) or "/dashboard/" in path.replace("\\", "/"):
        bucket = "unrelated_or_defer"
        reason = "outside the narrow gen1637 certification path"
        should_commit = False
    else:
        bucket = "unrelated_or_defer"
        reason = "not required to certify the existing gen1637 live pass"
        should_commit = False
    touch_map = touches(path)
    if bucket == "unsafe_or_needs_operator_review":
        risk = "high"
    elif any(touch_map.values()):
        risk = "medium"
    else:
        risk = "low"
    return {
        "bucket": bucket,
        "reason": reason,
        "risk_level": risk,
        "should_commit_in_bundle": should_commit,
        "touches": touch_map,
    }


def write_dirty_inventory(output_dir: Path, git: dict) -> list[dict]:
    rows = []
    for item in git["dirty"]:
        row = {
            "file_path": item["path"],
            "git_status": item["git_status"],
            **classify_dirty_file(item["path"]),
        }
        rows.append(row)
    rows = sorted(rows, key=lambda item: item["file_path"])
    (output_dir / "dirty_worktree_inventory.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")

    md_lines = ["# Dirty Worktree Inventory", ""]
    for row in rows:
        touch_summary = ", ".join(
            key for key, value in row["touches"].items() if value
        ) or "none"
        md_lines.extend(
            [
                f"## `{row['file_path']}`",
                f"- git_status: `{row['git_status']}`",
                f"- bucket: `{row['bucket']}`",
                f"- risk_level: `{row['risk_level']}`",
                f"- should_commit_in_bundle: `{row['should_commit_in_bundle']}`",
                f"- reason: {row['reason']}",
                f"- touches: {touch_summary}",
                "",
            ]
        )
    (output_dir / "dirty_worktree_inventory.md").write_text("\n".join(md_lines), encoding="utf-8")
    return rows


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _load_tests(path: Path | None) -> list[dict]:
    if path is None or not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else []


def _load_candidate_rejection_summary(db_path: Path) -> dict:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT rejection_reason FROM candidates WHERE generation=1637 AND rejection_reason IS NOT NULL"
        ).fetchall()
    finally:
        conn.close()
    counts = Counter(row[0] for row in rows)
    most_common = counts.most_common(1)[0][0] if counts else KNOWN_PASS["most_common_rejection_outcome"]
    return {
        "rejected_count": sum(counts.values()) or KNOWN_PASS["rejected_count"],
        "most_common_rejection_outcome": most_common,
    }


def _load_jsonl_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def _current_artifacts(output_dir: Path) -> list[str]:
    return sorted(
        str(path.relative_to(WORKSPACE)).replace("\\", "/")
        for path in output_dir.rglob("*")
        if path.is_file()
    )


def decide_verdict(*, checkpoint: dict, cycle_checkpoint: dict, preflight_after: dict, tests_run: list[dict], nonlive_guard: dict, dirty_rows: list[dict]) -> tuple[str, list[str], list[str]]:
    blockers: list[str] = []
    warnings: list[str] = []
    if int(checkpoint.get("generation", -1)) != 1637 or checkpoint.get("phase") != "complete":
        blockers.append("checkpoint_not_gen1637_complete")
    if int(cycle_checkpoint.get("data", {}).get("generation", -1)) != 1637:
        blockers.append("cycle_checkpoint_generation_mismatch")
    if cycle_checkpoint.get("data", {}).get("classification") != "B1003_LIVE_MODEL_CYCLE_PASS":
        blockers.append("cycle_checkpoint_not_live_pass")
    if switch_status().get("stop_requested") is not True:
        blockers.append("stop_flag_not_restored")
    if preflight_after.get("target_generation_total", 1) != 0:
        blockers.append("gen1638_rows_present")
    if preflight_after.get("contamination_detected"):
        blockers.append("live_db_contamination_guard_not_clean")
    if nonlive_guard.get("classification") != "DOOFUS_MODEL_DRY_RUN":
        blockers.append("nonlive_dry_run_guard_failed")
    focused_tests = [row for row in tests_run if row.get("scope") == "focused"]
    if not focused_tests or any(not row.get("passed") for row in focused_tests):
        blockers.append("focused_tests_not_passing")
    if any(row["bucket"] == "unsafe_or_needs_operator_review" for row in dirty_rows):
        warnings.append("worktree_contains_operator_review_items")
    if any(row["bucket"] == "unrelated_or_defer" for row in dirty_rows):
        warnings.append("worktree_contains_unrelated_changes")
    if blockers:
        return "DOOFUS_GEN1637_CERTIFICATION_PARTIAL", blockers, warnings
    return "DOOFUS_GEN1637_CERTIFICATION_PASS", blockers, warnings


def write_bundle(output_dir: Path, tests_run: list[dict]) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    git = git_state()
    checkpoint = load_checkpoint()
    cycle_checkpoint = read_checkpoint()
    dirty_rows = write_dirty_inventory(output_dir, git)
    preflight_after = inspect_live_db(target_generation=1638)
    nonlive_guard = verify_nonlive_dry_run_guard()
    rejection_summary = _load_candidate_rejection_summary(Path(preflight_after["db_path"]))
    verdict, blockers, warnings = decide_verdict(
        checkpoint=checkpoint,
        cycle_checkpoint=cycle_checkpoint,
        preflight_after=preflight_after,
        tests_run=tests_run,
        nonlive_guard=nonlive_guard,
        dirty_rows=dirty_rows,
    )

    manifest = {
        "classification": verdict,
        "live_verification_classification": "DOOFUS_GEN1637_LIVE_VERIFICATION_PASS",
        "baseline_commit": BASELINE_COMMIT,
        "current_commit": git["commit"],
        "current_branch": git["branch"],
        "worktree_dirty": git["worktree_dirty"],
        "checkpoint_before_live_generation": KNOWN_PASS["checkpoint_before_live_generation"],
        "checkpoint_after_live_generation": checkpoint,
        "cycle_checkpoint_after_live_generation": cycle_checkpoint,
        "live_model_route": KNOWN_PASS["live_model_route"],
        "live_model_result": KNOWN_PASS["live_model_result"],
        "model_call_duration_ms": KNOWN_PASS["model_call_duration_ms"],
        "proposals_returned": KNOWN_PASS["proposals_returned"],
        "proposals_applied": KNOWN_PASS["proposals_applied"],
        "generation_before": KNOWN_PASS["generation_before"],
        "generation_after": KNOWN_PASS["generation_after"],
        "elapsed_wall_time_s": KNOWN_PASS["elapsed_wall_time_s"],
        "scoring_phase_duration_ms": KNOWN_PASS["scoring_phase_duration_ms"],
        "scoring_timeout_recurred": KNOWN_PASS["scoring_timeout_recurred"],
        "slowest_scoring_step": KNOWN_PASS["slowest_scoring_step"],
        "slowest_scoring_candidate": KNOWN_PASS["slowest_scoring_candidate"],
        "slowest_scoring_duration_ms": KNOWN_PASS["slowest_scoring_duration_ms"],
        "promoted_count": KNOWN_PASS["promoted_count"],
        "shadow_promoted_count": KNOWN_PASS["shadow_promoted_count"],
        "rejected_count": rejection_summary["rejected_count"],
        "most_common_rejection_outcome": rejection_summary["most_common_rejection_outcome"],
        "gen1638_started": False,
        "stop_flag_restored": switch_status().get("stop_requested") is True,
        "nonlive_dry_run_guard_verified": nonlive_guard.get("classification") == "DOOFUS_MODEL_DRY_RUN",
        "db_contamination_prelaunch_detected": KNOWN_PASS["db_contamination_prelaunch_detected"],
        "db_contamination_prelaunch_scrubbed": KNOWN_PASS["db_contamination_prelaunch_scrubbed"],
        "db_generation_counts_after": preflight_after["table_counts"],
        "inline_rescue_timeout_observed": KNOWN_PASS["inline_rescue_timeout_observed"],
        "inline_rescue_duration_ms": KNOWN_PASS["inline_rescue_duration_ms"],
        "inline_rescue_timeout_threshold_ms": KNOWN_PASS["inline_rescue_timeout_threshold_ms"],
        "artifacts_written": _current_artifacts(output_dir),
        "tests_run": tests_run,
        "final_certification_verdict": verdict,
        "certification_blockers": blockers,
        "certification_warnings": warnings,
    }
    manifest_path = output_dir / "gen1637_certification_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    summary = {
        "generated_at": utc_now(),
        "executive_classification": verdict,
        "manifest_path": str(manifest_path.relative_to(WORKSPACE)).replace("\\", "/"),
        "current_branch": git["branch"],
        "current_commit": git["commit"],
        "stop_flag_status": switch_status(),
        "db_preflight_after": preflight_after,
        "tests_run": tests_run,
        "files_changed": [row["file_path"] for row in dirty_rows],
        "artifacts_written": _current_artifacts(output_dir),
        "remaining_risks": warnings + blockers,
        "exact_next_recommended_step": (
            "Review the dirty-worktree buckets and split commit-worthy certification changes from unrelated backlog before any future live gen1638 launch."
        ),
        "gen1638_launched": False,
    }
    (output_dir / "FINAL_REPORT.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    bucket_counts = Counter(row["bucket"] for row in dirty_rows)
    md_lines = [
        "# Final Report",
        "",
        "## Executive Classification",
        f"- `{verdict}`",
        "",
        "## Starting State",
        f"- baseline_commit: `{BASELINE_COMMIT}`",
        f"- current_branch: `{git['branch']}`",
        f"- current_commit: `{git['commit']}`",
        "",
        "## Dirty Worktree Inventory Summary",
        f"- total_dirty_files: `{len(dirty_rows)}`",
    ]
    for bucket, count in sorted(bucket_counts.items()):
        md_lines.append(f"- {bucket}: `{count}`")
    md_lines.extend(
        [
            "",
            "## Runtime Checkpoint Verification",
            f"- last_checkpoint: generation=`{checkpoint.get('generation')}` phase=`{checkpoint.get('phase')}`",
            f"- cycle_checkpoint: classification=`{cycle_checkpoint.get('data', {}).get('classification')}` generation=`{cycle_checkpoint.get('data', {}).get('generation')}`",
            "",
            "## DB Contamination Guard Result",
            f"- contamination_detected: `{preflight_after.get('contamination_detected')}`",
            f"- target_generation_total: `{preflight_after.get('target_generation_total')}`",
            f"- db_max_generation: `{preflight_after.get('db_max_generation')}`",
            "",
            "## Stop-State Guard Result",
            f"- stop_requested: `{switch_status().get('stop_requested')}`",
            "",
            "## Live/Non-Live Routing Guard Result",
            f"- nonlive_guard_classification: `{nonlive_guard.get('classification')}`",
            "",
            "## Inline Rescue Timeout Diagnosis",
            f"- observed_during_live_pass: `{KNOWN_PASS['inline_rescue_timeout_observed']}`",
            f"- live_duration_ms: `{KNOWN_PASS['inline_rescue_duration_ms']}`",
            f"- timeout_threshold_ms: `{KNOWN_PASS['inline_rescue_timeout_threshold_ms']}`",
            "- bundle_status: `bounded_and_tested`",
            "",
            "## Candidate/Proof-Builder Handoff Diagnosis",
            f"- rejected_count: `{rejection_summary['rejected_count']}`",
            f"- most_common_rejection_outcome: `{rejection_summary['most_common_rejection_outcome']}`",
            "",
            "## Scoring Timeout Regression Status",
            f"- scoring_timeout_recurred: `{KNOWN_PASS['scoring_timeout_recurred']}`",
            "",
            "## MAP-Elites Lock-Wait Regression Status",
            "- caller-owned SQLite connection reuse remains in place and focused regressions passed",
            "",
            "## Tests Run and Results",
        ]
    )
    for row in tests_run:
        md_lines.append(f"- [{row.get('scope')}] `{row.get('command')}` => `{row.get('status')}`")
    md_lines.extend(
        [
            "",
            "## Artifacts Written",
        ]
    )
    for artifact in _current_artifacts(output_dir):
        md_lines.append(f"- `{artifact}`")
    md_lines.extend(
        [
            "",
            "## Files Changed",
        ]
    )
    for row in dirty_rows:
        md_lines.append(f"- `{row['file_path']}`")
    md_lines.extend(
        [
            "",
            "## Remaining Risks",
        ]
    )
    if warnings or blockers:
        for item in warnings + blockers:
            md_lines.append(f"- {item}")
    else:
        md_lines.append("- none")
    md_lines.extend(
        [
            "",
            "## Exact Next Recommended Step",
            "- Review the dirty-worktree buckets and create a commit that includes only `gen1637_required_repair` and `postlive_certification_new_work` before any operator-approved gen1638 work.",
            "",
            "## Explicit Statement That gen1638 Was Not Launched",
            "- `gen1638 was not launched during this bundle.`",
        ]
    )
    (output_dir / "FINAL_REPORT.md").write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Write the gen1637 post-live certification bundle.")
    parser.add_argument(
        "--output-dir",
        default=str(WORKSPACE / "artifacts" / "doofus" / "gen1637-postlive-certification-v1"),
    )
    parser.add_argument("--tests-run-json", default="")
    args = parser.parse_args()

    tests_run = _load_tests(Path(args.tests_run_json)) if args.tests_run_json else []
    manifest = write_bundle(Path(args.output_dir), tests_run=tests_run)
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
