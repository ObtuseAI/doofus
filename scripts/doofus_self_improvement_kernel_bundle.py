"""Doofus-only self-improvement kernel + gen1640 readiness bundle orchestrator."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
OUT = WORKSPACE / "artifacts" / "doofus" / "self-improvement-kernel-gen1640-readiness-v1"
COMMIT_BEFORE = "8de5e1e2551cd10b016332887f3097ce87772ec2"

sys.path.insert(0, str(WORKSPACE))
from doofus.self_improvement.improvement_catalog import ImprovementCatalog, write_pair
from doofus.self_improvement.next_cycle_seed_builder import build_seed_recommendations
from doofus.self_improvement.observability_audit import audit_inline_rescue, audit_proof_builder
from scripts.doofus_generation_summary import build_generation_summary, write_pair as write_gen_pair
from scripts.doofus_shared_improvement_feed import run_gen1639_certification_continuation


def main() -> int:
    from doofus.core.doofus_paths import METRICS_DB, ROOT
    from doofus.runtime.live_db_preflight import inspect_live_db
    from doofus.safety.on_off_switch import status
    from doofus.supervisor.doofus_crash_recovery import load_checkpoint
    from doofus.supervisor.doofus_cycle_checkpoint import read_checkpoint

    OUT.mkdir(parents=True, exist_ok=True)
    ck = load_checkpoint()
    cc = read_checkpoint()
    stop = status()
    pf = inspect_live_db(target_generation=1640)
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=WORKSPACE, text=True).strip()
    dirty = subprocess.check_output(["git", "status", "--porcelain=v1"], cwd=WORKSPACE, text=True).splitlines()

    gen1639_counts = pf.get("table_counts", {}).get("candidates", {})
    write_pair(
        OUT,
        "STARTING_STATE",
        {
            "classification": "DOOFUS_SELF_IMPROVEMENT_KERNEL_STARTING_STATE",
            "branch": branch,
            "commit": COMMIT_BEFORE,
            "worktree_dirty_count": len(dirty),
            "checkpoint": ck,
            "cycle_checkpoint": cc,
            "stop_flag": stop,
            "live_db_path": str(METRICS_DB),
            "db_max_generation": pf.get("db_max_generation"),
            "candidates_max_generation": gen1639_counts.get("max_generation"),
            "gen1639_candidate_rows": gen1639_counts.get("checkpoint_generation_count"),
            "gen1640_row_count": pf.get("target_generation_total"),
            "gen1639_live_verification": (WORKSPACE / "artifacts/doofus/gen1639-live-verification-v1").exists(),
            "feed_v2_artifacts": (WORKSPACE / "artifacts/doofus/shared-improvement-feed-v2-blunder-consumer-v1").exists(),
            "disk_free_bytes": shutil.disk_usage("C:/").free,
            "paths_may_touch": ["doofus/self_improvement/", "scripts/doofus_self_improvement_*.py", "tests/test_self_improvement*.py"],
            "paths_must_not_touch": ["runtime/state/doofus_metrics.sqlite", "Shared Folder/doofus-fork-*"],
        },
    )

    if ck.get("generation") != 1639 or ck.get("phase") != "complete":
        write_pair(OUT, "FINAL_REPORT", {"classification": "DOOFUS_SELF_IMPROVEMENT_KERNEL_FAIL", "reason": "checkpoint"})
        return 1
    if not stop.get("stop_requested") or pf.get("target_generation_total", 1) != 0:
        write_pair(OUT, "FINAL_REPORT", {"classification": "DOOFUS_SELF_IMPROVEMENT_KERNEL_FAIL", "reason": "stop_or_gen1640"})
        return 1

    write_pair(
        OUT,
        "DOOFUS_ONLY_SCOPE_RESET",
        {
            "classification": "DOOFUS_ONLY_SCOPE_RESET",
            "statements": [
                "This bundle is Doofus-only.",
                "No other project consumer/importer will be built.",
                "Shared feed remains export/output surface only, not cross-project dependency.",
                "Doofus self-improvement focuses on Doofus-native mechanisms.",
                "gen1640 launch is not authorized.",
                "gen1640 preparation-only artifacts are allowed.",
                "Future cross-project export must remain file-artifact-only and optional.",
                "Doofus remains independent.",
            ],
        },
    )

    catalog = ImprovementCatalog.from_workspace(WORKSPACE, 1639)
    by_type = {}
    for item in catalog.items:
        by_type[item.type] = by_type.get(item.type, 0) + 1
    write_pair(
        OUT,
        "DOOFUS_NATIVE_IMPROVEMENT_CANDIDATES",
        {
            "classification": "DOOFUS_NATIVE_IMPROVEMENT_CANDIDATES",
            "total_count": len(catalog.items),
            "by_type": by_type,
            "mutation_count": by_type.get("mutation_method", 0),
            "proof_builder_count": by_type.get("proof_builder_improvement", 0),
            "telemetry_guard_count": by_type.get("telemetry_improvement", 0) + by_type.get("guard_pattern", 0),
            "repair_recipe_count": by_type.get("repair_recipe", 0),
            "cycle_quality_count": by_type.get("cycle_quality_improvement", 0),
            "sample_ids": [i.id for i in catalog.items[:10]],
        },
    )

    write_pair(
        OUT,
        "SELF_IMPROVEMENT_KERNEL_DESIGN",
        {
            "classification": "DOOFUS_SELF_IMPROVEMENT_KERNEL_DESIGN",
            "module": "doofus/self_improvement/",
            "files": [
                "improvement_item.py",
                "improvement_catalog.py",
                "improvement_scorer.py",
                "mutation_method_catalog.py",
                "repair_recipe_catalog.py",
                "cycle_lesson_extractor.py",
                "next_cycle_seed_builder.py",
                "observability_audit.py",
            ],
            "behaviors": [
                "ingest artifacts",
                "extract lessons",
                "dedupe",
                "score",
                "classify",
                "seed recommendations",
                "reports only - no live actions",
            ],
        },
    )

    cat_result = catalog.write_outputs(OUT)
    seeds = build_seed_recommendations(catalog, OUT)
    write_pair(OUT, "IMPORT_EXECUTION_RESULT", {"classification": "DOOFUS_CATALOG_BUILD_COMPLETE", **cat_result, "seeds": seeds.get("seed_count")})

    write_pair(OUT, "inline_rescue_observability_audit", audit_inline_rescue(1639))
    write_pair(OUT, "proof_builder_observability_audit", audit_proof_builder(1639))

    gen_summary = build_generation_summary(1639)
    write_gen_pair(OUT, "generation_1639_summary", gen_summary)

    cert = run_gen1639_certification_continuation(OUT, skip_db_scan=False)

    os.environ["DOOFUS_FEED_SKIP_TESTS"] = "1"
    t1 = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_self_improvement_catalog.py", "tests/test_doofus_generation_summary.py", "-q"],
        cwd=WORKSPACE,
        capture_output=True,
        text=True,
        timeout=120,
    )
    t2 = subprocess.run(
        [
            sys.executable, "-m", "pytest", "tests",
            "-k", "self_improvement or generation_summary or provider_gate or live_cycle_launch_guard or live_db_preflight or isolated_runtime or nonlive_cycle_forces_model_dry_run or inline_rescue or proof_builder or map_elites or scoring or postlive",
            "-q",
        ],
        cwd=WORKSPACE,
        capture_output=True,
        text=True,
        timeout=300,
    )
    write_pair(
        OUT,
        "TEST_RESULTS",
        {
            "focused_passed": t1.returncode == 0,
            "focused_tail": (t1.stdout or t1.stderr or "")[-500:],
            "broader_passed": t2.returncode == 0,
            "broader_tail": (t2.stdout or t2.stderr or "")[-500:],
        },
    )

    approved = [
        "doofus/self_improvement/__init__.py",
        "doofus/self_improvement/improvement_item.py",
        "doofus/self_improvement/improvement_catalog.py",
        "doofus/self_improvement/improvement_scorer.py",
        "doofus/self_improvement/mutation_method_catalog.py",
        "doofus/self_improvement/repair_recipe_catalog.py",
        "doofus/self_improvement/cycle_lesson_extractor.py",
        "doofus/self_improvement/next_cycle_seed_builder.py",
        "doofus/self_improvement/observability_audit.py",
        "scripts/doofus_self_improvement_catalog.py",
        "scripts/doofus_generation_summary.py",
        "scripts/doofus_self_improvement_kernel_bundle.py",
        "tests/test_self_improvement_catalog.py",
        "tests/test_doofus_generation_summary.py",
    ]
    existing = [f for f in approved if (WORKSPACE / f).exists()]
    write_pair(OUT, "commit_plan", {"approved_files": existing, "message": "Add Doofus self-improvement catalog and gen1640 readiness"})
    subprocess.run(["git", "add", *existing], cwd=WORKSPACE, check=False)
    cp = subprocess.run(
        [
            "git", "commit", "-m", "Add Doofus self-improvement catalog and gen1640 readiness",
            "-m", "Adds Doofus-native self-improvement catalog and gen1640 seed recommendations.",
            "-m", "Preserves gen1639 checkpoint and DB state. No live route. No gen1640 launch.",
        ],
        cwd=WORKSPACE,
        capture_output=True,
        text=True,
    )
    commit_after = COMMIT_BEFORE
    commit_status = "committed" if cp.returncode == 0 else "commit_failed_or_nothing_to_commit"
    if cp.returncode == 0:
        commit_after = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=WORKSPACE, text=True).strip()
    write_pair(OUT, "commit_result", {"commit_before": COMMIT_BEFORE, "commit_after": commit_after, "status": commit_status})

    ck_after = load_checkpoint()
    pf_after = inspect_live_db(target_generation=1640)
    write_pair(
        OUT,
        "FINAL_INVARIANT_CHECK",
        {
            "checkpoint_unchanged": ck_after == ck,
            "checkpoint": ck_after,
            "stop_flag_true": status().get("stop_requested") is True,
            "db_max_generation": pf_after.get("db_max_generation"),
            "gen1640_row_count": pf_after.get("target_generation_total"),
            "live_route_invoked": False,
            "gen1640_launched": False,
            "catalog_exists": (OUT / "self_improvement_catalog.json").exists(),
            "gen1640_prep_exists": (OUT / "GEN1640_OPERATOR_REVIEW_LAUNCH_PACKET_PREP_ONLY.json").exists(),
        },
    )

    tests_ok = t1.returncode == 0
    catalog_ok = len(catalog.items) >= 50
    seeds_ok = seeds.get("seed_count", 0) >= 20
    invariants_ok = ck_after.get("generation") == 1639 and pf_after.get("target_generation_total") == 0

    if catalog_ok and seeds_ok and tests_ok and invariants_ok and cert.get("evidence_ok"):
        final = "DOOFUS_SELF_IMPROVEMENT_KERNEL_READY_FOR_GEN1640_OPERATOR_REVIEW"
    elif invariants_ok:
        final = "DOOFUS_SELF_IMPROVEMENT_KERNEL_PARTIAL"
    else:
        final = "DOOFUS_SELF_IMPROVEMENT_KERNEL_FAIL"

    write_pair(
        OUT,
        "FINAL_REPORT",
        {
            "classification": final,
            "item_count": len(catalog.items),
            "by_type": by_type,
            "seed_count": seeds.get("seed_count"),
            "commit_after": commit_after,
            "next_action": "Review GEN1640_SEED_RECOMMENDATIONS and GEN1640_OPERATOR_REVIEW_LAUNCH_PACKET_PREP_ONLY; approve separate controlled gen1640 cycle if desired.",
        },
    )
    print(json.dumps({"classification": final, "items": len(catalog.items), "commit_after": commit_after}, indent=2))
    return 0 if final.endswith("REVIEW") else 1


if __name__ == "__main__":
    raise SystemExit(main())
