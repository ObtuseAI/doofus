"""Feed V2 + Blunder consumer readiness bundle orchestrator."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
OUT = WORKSPACE / "artifacts" / "doofus" / "shared-improvement-feed-v2-blunder-consumer-v1"
COMMIT_BEFORE = "2439fa07e6d08fcd8a7cfe61a29bcf32017463da"

sys.path.insert(0, str(WORKSPACE))
from scripts.doofus_shared_feed_v2 import (
    CURRENT_COMMIT,
    FORK_PATH,
    LEAN_FEED,
    audit_full_fork,
    build_v2_indexes,
    emit_blunder_consumer_package,
    load_feed_items_from_latest,
    validate_lean_feed,
    verify_feed_v2,
    write_pair,
)
from scripts.doofus_shared_improvement_feed import feed_schema, run_gen1639_certification_continuation


def main() -> int:
    from doofus.core import doofus_paths
    from doofus.runtime.live_db_preflight import inspect_live_db
    from doofus.safety.on_off_switch import status
    from doofus.supervisor.doofus_crash_recovery import load_checkpoint
    from doofus.supervisor.doofus_cycle_checkpoint import read_checkpoint

    OUT.mkdir(parents=True, exist_ok=True)
    ck = load_checkpoint()
    cc = read_checkpoint()
    stop = status()
    pf = inspect_live_db(target_generation=1640)
    dirty = subprocess.check_output(["git", "status", "--porcelain=v1"], cwd=WORKSPACE, text=True).splitlines()
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=WORKSPACE, text=True).strip()

    lean_size = sum(p.stat().st_size for p in LEAN_FEED.rglob("*") if p.is_file()) if LEAN_FEED.exists() else 0
    lean_items = len(list((LEAN_FEED / "latest").glob("*.json"))) if (LEAN_FEED / "latest").exists() else 0
    fork_size = sum(p.stat().st_size for p in FORK_PATH.rglob("*") if p.is_file()) if FORK_PATH.exists() else 0
    fork_commit = None
    if FORK_PATH.exists() and (FORK_PATH / ".git").exists():
        try:
            fork_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=FORK_PATH, text=True).strip()
        except subprocess.CalledProcessError:
            pass

    manifest = {}
    if (LEAN_FEED / "MANIFEST.json").exists():
        manifest = json.loads((LEAN_FEED / "MANIFEST.json").read_text(encoding="utf-8"))

    write_pair(
        OUT,
        "STARTING_STATE",
        {
            "classification": "DOOFUS_FEED_V2_STARTING_STATE",
            "branch": branch,
            "commit": COMMIT_BEFORE,
            "worktree_dirty_count": len(dirty),
            "checkpoint": ck,
            "cycle_checkpoint": cc,
            "stop_flag": stop,
            "db_max_generation": pf.get("db_max_generation"),
            "gen1640_row_count": pf.get("target_generation_total"),
            "lean_feed_path": str(LEAN_FEED),
            "lean_feed_size_bytes": lean_size,
            "lean_feed_item_count": lean_items,
            "lean_feed_manifest": manifest,
            "full_fork_path": str(FORK_PATH),
            "full_fork_size_bytes": fork_size,
            "full_fork_commit": fork_commit,
            "free_space_bytes": shutil.disk_usage(LEAN_FEED.drive + "\\").free if LEAN_FEED.exists() else 0,
            "gen1640_prep_packet": str(OUT.parent / "shared-improvement-feed-v1/GEN1640_OPERATOR_REVIEW_LAUNCH_PACKET_PREP_ONLY.json"),
        },
    )

    if ck.get("generation") != 1639 or not stop.get("stop_requested") or pf.get("target_generation_total", 1) != 0:
        write_pair(OUT, "FINAL_REPORT", {"classification": "DOOFUS_SHARED_FEED_V2_AND_BLUNDER_CONSUMER_READY_FAIL", "reason": "runtime_guard"})
        return 1

    if not LEAN_FEED.exists():
        write_pair(OUT, "FINAL_REPORT", {"classification": "DOOFUS_SHARED_FEED_V2_AND_BLUNDER_CONSUMER_READY_FAIL", "reason": "lean_feed_missing"})
        return 1

    # Phase 1
    fork_audit = audit_full_fork()
    write_pair(OUT, "FULL_FORK_COLD_BACKUP_AUDIT", fork_audit)

    # Phase 2
    schema = feed_schema()
    schema["version"] = "2.0.0"
    lean_validation = validate_lean_feed(LEAN_FEED, schema)
    write_pair(OUT, "LEAN_FEED_INTEGRITY_VALIDATION", lean_validation)

    # Phase 3
    items = load_feed_items_from_latest(LEAN_FEED)
    if len(items) < 42:
        from scripts.doofus_shared_improvement_feed import build_feed_items, publish_feed, build_blunder_bundle, mine_discoveries
        items = build_feed_items()
        publish_feed(
            staging_root=OUT,
            dest_root=LEAN_FEED,
            items=items,
            schema=schema,
            mined=mine_discoveries(),
            blunder_bundle=build_blunder_bundle(items),
        )
        items = load_feed_items_from_latest(LEAN_FEED)

    index_result = build_v2_indexes(LEAN_FEED, items)
    write_pair(OUT, "FEED_V2_INDEX_BUILD_RESULT", index_result)

    # Phase 4-5
    consumer_result = emit_blunder_consumer_package(LEAN_FEED, items)

    # Phase 7 publish plan/result (in-place V2 upgrade, no full republish)
    write_pair(
        OUT,
        "FEED_V2_PUBLISH_PLAN",
        {
            "classification": "DOOFUS_FEED_V2_PUBLISH_PLAN",
            "mode": "in_place_v2_upgrade",
            "dest": str(LEAN_FEED),
            "exclude_db": True,
            "exclude_secrets": True,
            "exclude_full_fork_copy": True,
            "estimated_size_bytes": lean_size,
        },
    )
    write_pair(
        OUT,
        "FEED_V2_PUBLISH_RESULT",
        {
            "classification": "DOOFUS_FEED_V2_PUBLISH_COMPLETE",
            "dest": str(LEAN_FEED),
            "indexes": index_result.get("indexes_written"),
            "consumer_package": consumer_result.get("path"),
        },
    )

    # Phase 8
    v2_verify = verify_feed_v2(LEAN_FEED)
    write_pair(OUT, "FEED_V2_VERIFICATION", v2_verify)

    # Phase 9
    cert = run_gen1639_certification_continuation(OUT, skip_db_scan=False)
    live_evidence = (WORKSPACE / "artifacts/doofus/gen1639-live-verification-v1/FINAL_REPORT.json").exists()
    write_pair(
        OUT,
        "GEN1639_CERTIFICATION_CONTINUATION",
        {
            "classification": "DOOFUS_GEN1639_CERTIFICATION_CONTINUATION",
            "live_evidence_present": live_evidence,
            "preflight": cert.get("preflight"),
            "manifest": cert.get("manifest"),
            "live_route_invoked": False,
        },
    )

    os.environ["DOOFUS_FEED_SKIP_TESTS"] = "1"
    test_feed = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_shared_feed_v2.py", "-q"],
        cwd=WORKSPACE,
        capture_output=True,
        text=True,
        timeout=120,
    )
    write_pair(OUT, "test_results", {"feed_v2_tests_passed": test_feed.returncode == 0, "tail": (test_feed.stdout or test_feed.stderr or "")[-400:]})

    commit_after = COMMIT_BEFORE
    commit_status = "pending"
    approved = [
        "scripts/doofus_shared_feed_v2.py",
        "scripts/doofus_shared_feed_v2_blunder_consumer_bundle.py",
        "scripts/doofus_shared_improvement_feed.py",
        "tests/test_shared_feed_v2.py",
    ]
    existing = [f for f in approved if (WORKSPACE / f).exists()]
    if existing:
        write_pair(OUT, "commit_plan", {"approved_files": existing, "message": "Add shared feed V2 indexes and Blunder consumer package"})
        subprocess.run(["git", "add", *existing], cwd=WORKSPACE, check=False)
        cp = subprocess.run(
            [
                "git", "commit", "-m", "Add shared feed V2 indexes and Blunder consumer package",
                "-m", "Adds V2 feed indexes and deterministic scoring.",
                "-m", "Adds Blunder consumer/importer package generation.",
                "-m", "Audits full fork as optional cold backup.",
                "-m", "No DBs or secrets copied. No live route. No gen1640 launch.",
            ],
            cwd=WORKSPACE,
            capture_output=True,
            text=True,
        )
        if cp.returncode == 0:
            commit_after = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=WORKSPACE, text=True).strip()
            commit_status = "committed"
        else:
            commit_status = "commit_failed_or_nothing_to_commit"
    write_pair(OUT, "commit_result", {"commit_before": COMMIT_BEFORE, "commit_after": commit_after, "status": commit_status})

    lean_ok = lean_validation.get("classification", "").endswith("PASS")
    v2_ok = v2_verify.get("classification", "").endswith("PASS")
    fork_ok = fork_audit.get("path_exists")

    if lean_ok and v2_ok and fork_ok and cert.get("evidence_ok"):
        final = "DOOFUS_SHARED_FEED_V2_AND_BLUNDER_CONSUMER_READY_PASS"
    elif ck.get("generation") == 1639:
        final = "DOOFUS_SHARED_FEED_V2_AND_BLUNDER_CONSUMER_READY_PARTIAL"
    else:
        final = "DOOFUS_SHARED_FEED_V2_AND_BLUNDER_CONSUMER_READY_FAIL"

    total_size = sum(p.stat().st_size for p in LEAN_FEED.rglob("*") if p.is_file())
    write_pair(
        OUT,
        "FINAL_REPORT",
        {
            "classification": final,
            "fork_audit": fork_audit.get("classification"),
            "lean_validation": lean_validation.get("classification"),
            "index_build": index_result.get("classification"),
            "consumer_package": consumer_result.get("classification"),
            "v2_verification": v2_verify.get("classification"),
            "commit_after": commit_after,
            "feed_size_bytes": total_size,
            "full_fork_safe_to_delete_recommendation": fork_audit.get("safe_to_delete_if_lean_feed_sufficient"),
            "next_action": "Use BLUNDER_FEED_CONSUMER_BUILD_PROMPT.md in a Blunder-side session.",
        },
    )

    print(json.dumps({"classification": final, "commit_after": commit_after, "feed_size": total_size}, indent=2))
    return 0 if final.endswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
