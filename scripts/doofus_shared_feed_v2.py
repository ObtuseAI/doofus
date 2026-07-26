"""Feed V2: scoring, indexes, fork audit, Blunder consumer package."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

WORKSPACE = Path(__file__).resolve().parents[1]
LEAN_FEED = Path(r"C:\Users\developer\Desktop\Shared Folder\doofus-improvement-feed")
FORK_PATH = Path(r"C:\Users\developer\Desktop\Shared Folder\doofus-fork-gen1639-certified-20260704T201846Z")
EXPORT_START_COMMIT = "018c880b48a4821ee391bbb150ad81942d240d9b"
CURRENT_COMMIT = "2439fa07e6d08fcd8a7cfe61a29bcf32017463da"

SECRET_NAMES = {".env", ".env.local", "doofusapi", "doofusapi.txt", "doofusapi.env"}
DB_SUFFIXES = {".sqlite", ".sqlite-wal", ".sqlite-shm", ".db"}
FEED_V2_SIZE_CAP = 5 * 1024 * 1024
MAX_FILE_V2 = 1024 * 1024

PRIORITY_TIERS = [
    "P0_IMPORT_NOW",
    "P1_IMPORT_NEXT",
    "P2_USE_AS_REFERENCE",
    "P3_REVIEW_LATER",
    "DO_NOT_IMPORT_DIRECTLY",
]


def utc_now() -> str:
    from datetime import datetime, timezone
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


def _fork_walk_stats(root: Path, top_n: int = 50) -> dict[str, Any]:
    """Single-pass walk for fork audit (avoids repeated rglob on large trees)."""
    total = 0
    db_count = 0
    backup_like_count = 0
    archive_count = 0
    top: list[tuple[int, str]] = []
    archive_suffixes = {".zip", ".7z", ".tar", ".gz"}
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            p = Path(dirpath) / name
            try:
                size = p.stat().st_size
            except OSError:
                continue
            total += size
            suffix = p.suffix.lower()
            if suffix in DB_SUFFIXES:
                db_count += 1
            if "backup" in name.lower() or "scrub" in str(p).lower():
                backup_like_count += 1
            if suffix in archive_suffixes:
                archive_count += 1
            rel = str(p.relative_to(root))
            if len(top) < top_n:
                top.append((size, rel))
                top.sort(key=lambda x: -x[0])
            elif size > top[-1][0]:
                top[-1] = (size, rel)
                top.sort(key=lambda x: -x[0])
    top.sort(key=lambda x: -x[0])
    return {
        "total_size_bytes": total,
        "db_file_count": db_count,
        "db_backup_like_count": backup_like_count,
        "archive_file_count": archive_count,
        "largest_50_files": [{"path": rel, "size_bytes": size} for size, rel in top[:top_n]],
    }


def audit_full_fork() -> dict:
    exists = FORK_PATH.exists()
    audit: dict[str, Any] = {
        "classification": "DOOFUS_FULL_FORK_COLD_BACKUP_AUDIT",
        "fork_path": str(FORK_PATH),
        "path_exists": exists,
        "role": "OPTIONAL_COLD_BACKUP_NOT_PRIMARY_FEED",
        "primary_handoff": str(LEAN_FEED),
        "export_start_commit": EXPORT_START_COMMIT,
        "export_end_commit_observed": None,
        "commit_mismatch_reason": "export began at 018c880; feed commit 2439fa0 landed during overlapping robocopy",
    }
    if not exists:
        audit["useful_as_cold_backup"] = False
        audit["safe_to_delete_if_lean_feed_sufficient"] = None
        return audit

    walk = _fork_walk_stats(FORK_PATH, 50)

    fork_commit = None
    if (FORK_PATH / ".git").exists():
        try:
            fork_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=FORK_PATH, text=True).strip()
        except subprocess.CalledProcessError:
            fork_commit = None
    audit["export_end_commit_observed"] = fork_commit
    audit["source_commit_match"] = fork_commit == EXPORT_START_COMMIT

    ck, cc, stop = None, None, None
    ck_path = FORK_PATH / "runtime" / "state" / "last_checkpoint.json"
    cc_path = FORK_PATH / "runtime" / "state" / "cycle_checkpoint.json"
    stop_path = FORK_PATH / "runtime" / "control" / "DOOFUS_STOP.request"
    if ck_path.exists():
        ck = json.loads(ck_path.read_text(encoding="utf-8"))
    if cc_path.exists():
        cc = json.loads(cc_path.read_text(encoding="utf-8"))
    stop = stop_path.exists()

    audit.update(
        {
            "total_size_bytes": walk["total_size_bytes"],
            "total_size_gb": round(walk["total_size_bytes"] / 1e9, 2),
            "largest_50_files": walk["largest_50_files"],
            "db_file_count": walk["db_file_count"],
            "db_backup_like_count": walk["db_backup_like_count"],
            "archive_file_count": walk["archive_file_count"],
            "git_exists": (FORK_PATH / ".git").exists(),
            "fork_commit": fork_commit,
            "checkpoint": ck,
            "cycle_checkpoint": cc,
            "stop_flag_file_present": stop,
            "gen1639_artifacts_present": (FORK_PATH / "artifacts/doofus/gen1639-live-verification-v1").exists(),
            "live_db_backup_present": (FORK_PATH / "runtime/state/doofus_metrics_gen1639_certified_backup.sqlite").exists()
            or (FORK_PATH / "runtime/state/doofus_metrics.sqlite").exists(),
            "checksums_present": (FORK_PATH / "CHECKSUMS.sha256").exists(),
            "restore_notes_present": (FORK_PATH / "RESTORE_NOTES.md").exists(),
            "export_manifest_present": (FORK_PATH / "EXPORT_MANIFEST.json").exists(),
            "useful_as_cold_backup": True,
            "safe_to_delete_if_lean_feed_sufficient": True,
            "safe_to_delete_note": "Operator approval required before deletion. Lean feed is primary handoff.",
            "recommend_move_to_archive": False,
            "recommend_label": "OPTIONAL_COLD_BACKUP_NOT_PRIMARY_FEED",
        }
    )

    marker = (
        "# Optional Cold Backup - Not Primary Feed\n\n"
        "This full fork is **not** the primary cross-project feed.\n\n"
        f"- Primary shared handoff: `{LEAN_FEED}`\n"
        "- This fork may contain large DB backups (~42GB+ each).\n"
        "- Do not use for routine feed consumption.\n"
        f"- Commit mismatch expected: export started at `{EXPORT_START_COMMIT}`; "
        f"fork `.git` may show `{fork_commit or 'unknown'}`.\n"
        "- **Do not delete unless operator explicitly approves.**\n"
    )
    try:
        (FORK_PATH / "OPTIONAL_COLD_BACKUP_NOT_PRIMARY_FEED.md").write_text(marker, encoding="utf-8")
        audit["marker_written"] = True
    except OSError as exc:
        audit["marker_written"] = False
        audit["marker_error"] = str(exc)

    return audit


def load_feed_items_from_latest(feed_root: Path) -> list[dict]:
    latest = feed_root / "latest"
    items = []
    for p in sorted(latest.glob("*.json")):
        try:
            items.append(json.loads(p.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            pass
    return items


def score_item(item: dict) -> dict:
    """Deterministic scoring from item fields."""
    type_ = item.get("type", "")
    primary = item.get("primary_target", "")
    risk = item.get("risk_level", "low")
    status = item.get("status", "draft")
    blunder_rel = bool(item.get("blunder_relevance"))

    type_weight = {
        "guard_pattern": 90,
        "repair_recipe": 85,
        "test_pattern": 80,
        "mutation_method": 75,
        "architecture_lesson": 70,
        "risk_control": 70,
        "operator_packet": 65,
        "telemetry_lesson": 55,
        "recommendation": 50,
        "improvement": 50,
        "variant": 45,
        "cross_project_transfer": 60,
        "prompt_pattern": 55,
    }.get(type_, 40)

    blunder_score = 30
    if primary == "blunder":
        blunder_score = 95
    elif "blunder" in item.get("target_projects", []):
        blunder_score = 80
    elif blunder_rel:
        blunder_score = 70

    risk_score = {"low": 10, "medium": 40, "high": 70}.get(risk, 30)
    validation_strength = 90 if status == "validated" else 50 if status == "usable" else 20

    utility = min(100, int(type_weight * 0.4 + blunder_score * 0.35 + validation_strength * 0.25))
    blunder_relevance_score = blunder_score
    difficulty = 30 if type_ in ("guard_pattern", "test_pattern") else 50 if type_ == "mutation_method" else 40

    if utility >= 85 and blunder_score >= 80 and risk_score <= 30:
        priority = "P0_IMPORT_NOW"
        action = "import_as_blunder_native_pattern"
    elif utility >= 70 and blunder_score >= 60:
        priority = "P1_IMPORT_NEXT"
        action = "queue_for_blunder_validation"
    elif utility >= 50:
        priority = "P2_USE_AS_REFERENCE"
        action = "reference_only_until_validated"
    elif type_ == "operator_packet" and primary == "doofus":
        priority = "DO_NOT_IMPORT_DIRECTLY"
        action = "doofus_only_operator_context"
    elif utility >= 35:
        priority = "P3_REVIEW_LATER"
        action = "review_when_building_related_feature"
    else:
        priority = "DO_NOT_IMPORT_DIRECTLY"
        action = "skip_or_archive"

    return {
        "utility_score": utility,
        "blunder_relevance_score": blunder_relevance_score,
        "implementation_difficulty": difficulty,
        "risk_score": risk_score,
        "validation_strength": validation_strength,
        "recommended_import_priority": priority,
        "recommended_consumer_action": action,
    }


def build_v2_indexes(feed_root: Path, items: list[dict]) -> dict:
    scored: list[dict] = []
    for item in items:
        scores = score_item(item)
        enriched = {**item, **scores}
        scored.append(enriched)

    dedupe_index = {i["dedupe_key"]: i["id"] for i in scored}
    project_index: dict[str, list[str]] = {}
    type_index: dict[str, list[str]] = {}
    tag_index: dict[str, list[str]] = {}
    for i in scored:
        project_index.setdefault(i.get("primary_target", "general"), []).append(i["dedupe_key"])
        type_index.setdefault(i.get("type", "unknown"), []).append(i["dedupe_key"])
        for t in i.get("tags", []):
            tag_index.setdefault(t, []).append(i["dedupe_key"])

    blunder_priority = sorted(
        [i for i in scored if "blunder" in i.get("target_projects", []) or i.get("primary_target") == "blunder"],
        key=lambda x: (-x["utility_score"], -x["blunder_relevance_score"]),
    )
    priority_index = {
        tier: [{"id": i["id"], "dedupe_key": i["dedupe_key"], "title": i["title"]} for i in scored if i["recommended_import_priority"] == tier]
        for tier in PRIORITY_TIERS
    }

    def _type_subindex(type_name: str) -> dict:
        subset = [i for i in scored if i.get("type") == type_name]
        return {
            "count": len(subset),
            "items": [{"id": i["id"], "dedupe_key": i["dedupe_key"], "title": i["title"], "priority": i["recommended_import_priority"]} for i in subset],
        }

    indexes_dir = feed_root / "indexes"
    indexes_dir.mkdir(parents=True, exist_ok=True)

    item_index = {
        "classification": "DOOFUS_FEED_V2_ITEM_INDEX",
        "version": "2.0.0",
        "created_at_utc": utc_now(),
        "item_count": len(scored),
        "items": [
            {
                "id": i["id"],
                "dedupe_key": i["dedupe_key"],
                "title": i["title"],
                "type": i["type"],
                "primary_target": i["primary_target"],
                **{k: i[k] for k in score_item(i).keys()},
            }
            for i in scored
        ],
    }
    payloads = {
        "ITEM_INDEX": item_index,
        "DEDUPE_INDEX": {"classification": "DOOFUS_FEED_V2_DEDUPE_INDEX", "dedupe_keys": dedupe_index},
        "PROJECT_INDEX": {"classification": "DOOFUS_FEED_V2_PROJECT_INDEX", "projects": project_index},
        "TYPE_INDEX": {"classification": "DOOFUS_FEED_V2_TYPE_INDEX", "types": type_index},
        "TAG_INDEX": {"classification": "DOOFUS_FEED_V2_TAG_INDEX", "tags": tag_index},
        "BLUNDER_PRIORITY_INDEX": {
            "classification": "DOOFUS_FEED_V2_BLUNDER_PRIORITY_INDEX",
            "ordered": [{"id": i["id"], "dedupe_key": i["dedupe_key"], "title": i["title"], "priority": i["recommended_import_priority"]} for i in blunder_priority],
            "by_priority_tier": priority_index,
        },
        "MUTATION_METHOD_INDEX": {"classification": "DOOFUS_FEED_V2_MUTATION_METHOD_INDEX", **_type_subindex("mutation_method")},
        "REPAIR_RECIPE_INDEX": {"classification": "DOOFUS_FEED_V2_REPAIR_RECIPE_INDEX", **_type_subindex("repair_recipe")},
        "TEST_PATTERN_INDEX": {"classification": "DOOFUS_FEED_V2_TEST_PATTERN_INDEX", **_type_subindex("test_pattern")},
        "GUARD_PATTERN_INDEX": {"classification": "DOOFUS_FEED_V2_GUARD_PATTERN_INDEX", **_type_subindex("guard_pattern")},
    }

    for name, payload in payloads.items():
        (indexes_dir / f"{name}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        md_lines = [f"# {name.replace('_', ' ').title()}", "", f"Items: `{payload.get('item_count', payload.get('count', 'see json'))}`", ""]
        (indexes_dir / f"{name}.md").write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    # Update latest JSON files with scores (compact patch files in indexes/scored/)
    scored_dir = indexes_dir / "scored"
    scored_dir.mkdir(exist_ok=True)
    for i in scored:
        patch = {k: i[k] for k in score_item(i).keys()}
        (scored_dir / f"{i['dedupe_key']}.json").write_text(json.dumps(patch, indent=2), encoding="utf-8")

    manifest_path = feed_root / "MANIFEST.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["feed_version"] = "2.0.0"
        manifest["v2_indexes"] = list(payloads.keys())
        manifest["scored_item_count"] = len(scored)
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    return {
        "classification": "DOOFUS_FEED_V2_INDEX_BUILD_COMPLETE",
        "indexes_written": list(payloads.keys()),
        "item_count": len(scored),
        "p0_count": len(priority_index.get("P0_IMPORT_NOW", [])),
        "p1_count": len(priority_index.get("P1_IMPORT_NEXT", [])),
    }


def validate_lean_feed(feed_root: Path, schema: dict) -> dict:
    from scripts.doofus_shared_improvement_feed import validate_feed_item, SECRET_NAMES, DB_SUFFIXES

    checks: dict[str, Any] = {}
    checks["readme_exists"] = (feed_root / "README.md").exists()
    checks["manifest_json_exists"] = (feed_root / "MANIFEST.json").exists()
    checks["manifest_md_exists"] = (feed_root / "MANIFEST.md").exists()
    checks["schema_exists"] = (feed_root / "FEED_SCHEMA.json").exists()
    checks["latest_exists"] = (feed_root / "latest").is_dir()
    checks["blunder_dir_exists"] = (feed_root / "by_project/blunder").is_dir()
    checks["by_type_exists"] = (feed_root / "by_type").is_dir()

    latest_jsons = list((feed_root / "latest").glob("*.json")) if checks["latest_exists"] else []
    checks["feed_item_count"] = len(latest_jsons)
    checks["feed_item_count_ok"] = len(latest_jsons) >= 42

    schema_errors = []
    dedupe_keys = []
    md_missing = []
    for jp in latest_jsons:
        mp = jp.with_suffix(".md")
        if not mp.exists():
            md_missing.append(jp.name)
        try:
            data = json.loads(jp.read_text(encoding="utf-8"))
            schema_errors.extend(validate_feed_item(data, schema))
            dedupe_keys.append(data.get("dedupe_key"))
        except json.JSONDecodeError:
            schema_errors.append(jp.name)

    db_files = [p for p in feed_root.rglob("*") if p.suffix in DB_SUFFIXES]
    secrets = [p for p in feed_root.rglob("*") if p.name in SECRET_NAMES]
    env_files = [p for p in feed_root.rglob(".env*") if p.is_file()]
    total_size = sum(p.stat().st_size for p in feed_root.rglob("*") if p.is_file())

    manifest_count = None
    if checks["manifest_json_exists"]:
        manifest_count = json.loads((feed_root / "MANIFEST.json").read_text(encoding="utf-8")).get("item_count")

    checks.update(
        {
            "every_json_has_md": len(md_missing) == 0,
            "md_missing_count": len(md_missing),
            "schema_valid": len(schema_errors) == 0,
            "dedupe_unique": len(dedupe_keys) == len(set(dedupe_keys)),
            "no_db_files": len(db_files) == 0,
            "no_secrets": len(secrets) == 0,
            "no_env_files": len(env_files) == 0,
            "compact_size": total_size < FEED_V2_SIZE_CAP,
            "blunder_bundle_exists": (feed_root / "by_project/blunder/BLUNDER_RECOMMENDATION_BUNDLE.json").exists(),
            "manifest_count_matches": manifest_count == len(latest_jsons) if manifest_count is not None else None,
        }
    )

    passed = all(v for k, v in checks.items() if isinstance(v, bool))
    return {
        "classification": "DOOFUS_LEAN_FEED_INTEGRITY_PASS" if passed else "DOOFUS_LEAN_FEED_INTEGRITY_PARTIAL",
        "checks": checks,
        "total_size_bytes": total_size,
        "schema_error_count": len(schema_errors),
        "db_files_found": [str(p) for p in db_files[:5]],
    }


def emit_blunder_consumer_package(feed_root: Path, items: list[dict]) -> dict:
    pkg = feed_root / "by_project" / "blunder" / "consumer_package"
    pkg.mkdir(parents=True, exist_ok=True)

    scored = [{**i, **score_item(i)} for i in items]
    blunder_items = [i for i in scored if "blunder" in i.get("target_projects", []) or i.get("primary_target") == "blunder"]
    top10 = sorted(blunder_items, key=lambda x: (-x["utility_score"], -x["blunder_relevance_score"]))[:10]

    def by_type(t: str) -> list[dict]:
        return [i for i in blunder_items if i.get("type") == t]

    spec = {
        "classification": "DOOFUS_BLUNDER_CONSUMER_SPEC",
        "version": "1.0.0",
        "feed_root": str(feed_root),
        "rules": {
            "read_artifacts_as_files_only": True,
            "never_import_doofus_python_modules": True,
            "never_depend_on_doofus_runtime_db": True,
            "never_mutate_doofus_state": True,
            "copy_concepts_to_blunder_native_only_after_validation": True,
            "dedupe_by_stable_key": True,
            "assign_blunder_validation_status": True,
            "separate_recommendations_from_implementations": True,
            "preserve_provenance_to_feed_item_ids": True,
            "support_offline_no_llm_consumption": True,
            "support_llm_optional_summarization": True,
            "support_mutation_queue_generation": True,
            "support_repair_recipe_queue": True,
            "support_test_pattern_extraction": True,
            "support_guard_pattern_extraction": True,
        },
    }

    import_plan = {
        "classification": "DOOFUS_BLUNDER_IMPORT_PLAN",
        "phases": [
            {"phase": 1, "action": "Parse MANIFEST.json and indexes/BLUNDER_PRIORITY_INDEX.json"},
            {"phase": 2, "action": "Import P0/P1 items into Blunder improvement queue"},
            {"phase": 3, "action": "Build mutation-method, guard, test, repair catalogs"},
            {"phase": 4, "action": "Validate each idea in isolated Blunder rehearsal"},
            {"phase": 5, "action": "Write Blunder import report; no Doofus runtime coupling"},
        ],
    }

    files_written = []
    for stem, payload in [
        ("BLUNDER_CONSUMER_SPEC", spec),
        ("BLUNDER_IMPORT_PLAN", import_plan),
        ("BLUNDER_TOP_10_IMPORTS", {"classification": "DOOFUS_BLUNDER_TOP_10", "items": top10}),
        ("BLUNDER_MUTATION_METHODS", {"classification": "DOOFUS_BLUNDER_MUTATION_METHODS", "items": by_type("mutation_method")}),
        ("BLUNDER_GUARD_PATTERNS", {"classification": "DOOFUS_BLUNDER_GUARD_PATTERNS", "items": by_type("guard_pattern")}),
        ("BLUNDER_TEST_PATTERNS", {"classification": "DOOFUS_BLUNDER_TEST_PATTERNS", "items": by_type("test_pattern")}),
        ("BLUNDER_REPAIR_RECIPES", {"classification": "DOOFUS_BLUNDER_REPAIR_RECIPES", "items": by_type("repair_recipe")}),
    ]:
        (pkg / f"{stem}.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        (pkg / f"{stem}.md").write_text(f"# {stem.replace('_', ' ')}\n\nSee JSON for structured data.\n", encoding="utf-8")
        files_written.append(stem)

    (pkg / "README.md").write_text(
        "# Blunder Consumer Package\n\n"
        "Read-only consumption of Doofus improvement feed. **No Doofus runtime dependency.**\n\n"
        "Start with `BLUNDER_CONSUMER_SPEC.json` and `BLUNDER_FEED_CONSUMER_BUILD_PROMPT.md`.\n",
        encoding="utf-8",
    )
    (pkg / "BLUNDER_NO_RUNTIME_DEPENDENCY_RULES.md").write_text(
        "# No Runtime Dependency Rules\n\n"
        "1. Never `import doofus` or any Doofus submodule.\n"
        "2. Never open Doofus SQLite metrics DB.\n"
        "3. Never spawn Doofus supervisor or live cycles.\n"
        "4. Copy patterns into Blunder-native code after validation.\n"
        "5. Treat feed items as external knowledge artifacts only.\n",
        encoding="utf-8",
    )

    prompt = build_blunder_consumer_prompt(feed_root, top10)
    (pkg / "BLUNDER_SAFE_CONSUMPTION_PROMPT.md").write_text(prompt, encoding="utf-8")
    (pkg / "BLUNDER_FEED_CONSUMER_BUILD_PROMPT.md").write_text(prompt, encoding="utf-8")

    return {"classification": "DOOFUS_BLUNDER_CONSUMER_PACKAGE_COMPLETE", "path": str(pkg), "files": files_written}


def build_blunder_consumer_prompt(feed_root: Path, top10: list[dict]) -> str:
    top_lines = "\n".join(f"{n+1}. [{i.get('recommended_import_priority')}] {i['title']} (id={i['id']})" for n, i in enumerate(top10))
    return f"""# Blunder Feed Consumer Build Prompt

Paste this into a Blunder/Codex/Cursor session.

## Goal
Build a **Blunder-native** feed consumer that reads Doofus improvement artifacts as **files only**.

## Feed location
`{feed_root}`

## Steps
1. Parse `{feed_root}/MANIFEST.json`
2. Parse `{feed_root}/indexes/BLUNDER_PRIORITY_INDEX.json`
3. Import P0/P1 items from `by_project/blunder/` as Blunder-native ideas (not Doofus code)
4. Create local Blunder improvement queue with dedupe by `dedupe_key`
5. Create catalogs: mutation methods, guard patterns, test patterns, repair recipes
6. Validate every imported idea in isolated Blunder rehearsal before use
7. **Never** import Doofus Python modules
8. **Never** depend on Doofus DB or runtime state
9. **Never** run live external/provider actions during import
10. Write `BLUNDER_FEED_IMPORT_REPORT.md` with provenance back to feed item IDs
11. Produce safe next Blunder build plan

## Top 10 starting imports
{top_lines}

## Consumer package
Also read: `{feed_root}/by_project/blunder/consumer_package/BLUNDER_CONSUMER_SPEC.json`

## Hard rules
- File-artifact boundary only
- Offline/no-LLM consumption must work
- LLM optional for summarization later
- Separate recommendations from implemented changes
"""


def verify_feed_v2(feed_root: Path) -> dict:
    indexes_dir = feed_root / "indexes"
    pkg = feed_root / "by_project/blunder/consumer_package"
    required_indexes = [
        "ITEM_INDEX.json", "DEDUPE_INDEX.json", "PROJECT_INDEX.json", "TYPE_INDEX.json",
        "TAG_INDEX.json", "BLUNDER_PRIORITY_INDEX.json", "MUTATION_METHOD_INDEX.json",
        "REPAIR_RECIPE_INDEX.json", "TEST_PATTERN_INDEX.json", "GUARD_PATTERN_INDEX.json",
    ]
    db_files = [p for p in feed_root.rglob("*") if p.suffix in {".sqlite", ".db"}]
    secrets = [p for p in feed_root.rglob("*") if p.name in {".env", "doofusapi"}]
    total = sum(p.stat().st_size for p in feed_root.rglob("*") if p.is_file())
    largest = max((p for p in feed_root.rglob("*") if p.is_file()), key=lambda p: p.stat().st_size, default=None)
    latest_count = len(list((feed_root / "latest").glob("*.json"))) if (feed_root / "latest").exists() else 0

    priority = {}
    bp = indexes_dir / "BLUNDER_PRIORITY_INDEX.json"
    if bp.exists():
        priority = json.loads(bp.read_text(encoding="utf-8")).get("by_priority_tier", {})

    checks = {
        "indexes_exist": all((indexes_dir / n).exists() for n in required_indexes),
        "consumer_package_exists": pkg.exists(),
        "build_prompt_exists": (pkg / "BLUNDER_FEED_CONSUMER_BUILD_PROMPT.md").exists(),
        "item_count_ok": latest_count >= 42,
        "no_db_files": len(db_files) == 0,
        "no_secrets": len(secrets) == 0,
        "size_under_5mb": total <= FEED_V2_SIZE_CAP,
        "largest_under_1mb": (largest.stat().st_size if largest else 0) <= MAX_FILE_V2,
        "p0_exists": len(priority.get("P0_IMPORT_NOW", [])) > 0,
        "p1_exists": len(priority.get("P1_IMPORT_NEXT", [])) > 0,
        "blunder_priority_index_exists": bp.exists(),
    }

    sys.path.insert(0, str(WORKSPACE))
    from doofus.safety.on_off_switch import status
    from doofus.supervisor.doofus_crash_recovery import load_checkpoint

    ck = load_checkpoint()
    checks["checkpoint_gen1639"] = ck.get("generation") == 1639 and ck.get("phase") == "complete"
    checks["stop_flag_true"] = status().get("stop_requested") is True

    passed = all(checks.values())
    return {
        "classification": "DOOFUS_FEED_V2_VERIFICATION_PASS" if passed else "DOOFUS_FEED_V2_VERIFICATION_PARTIAL",
        "checks": checks,
        "total_size_bytes": total,
        "largest_file_bytes": largest.stat().st_size if largest else 0,
        "item_count": latest_count,
    }
