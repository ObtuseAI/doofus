"""Full gen1639-certified network fork export to Desktop Shared Folder."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]

SECRET_EXCLUDE_NAMES = {".env", ".env.local", "doofusapi", "doofusapi.txt", "doofusapi.env"}
COPY_EXCLUDE_DIRS = {".venv_doofus", "__pycache__", ".pytest_cache", "node_modules"}
COPY_EXCLUDE_SUFFIXES = {".pyc", ".pyo"}


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


def resolve_network_export_dir() -> tuple[Path | None, str, dict]:
    for env_name in ("DOOFUS_NETWORK_EXPORT_DIR", "DOOFUS_DESKTOP_NETWORK_SHARE", "NETWORK_SHARED_DESKTOP_FOLDER"):
        val = os.environ.get(env_name)
        if val:
            p = Path(val)
            return p, f"environment_variable:{env_name}", {"env_name": env_name}

    sys.path.insert(0, str(WORKSPACE))
    from doofus.core.doofus_paths import CANONICAL_SHARED, SHARED

    shared_parent = SHARED.parent if SHARED.name != "Shared Folder" else SHARED
    if shared_parent.name == "Doofus-Local-Operation":
        shared_parent = shared_parent.parent
    candidates = [
        (Path(r"C:\Users\developer\Desktop\Shared Folder"), "canonical:doofus_paths/README Desktop Shared Folder"),
        (shared_parent, "doofus_paths:SHARED.parent"),
        (CANONICAL_SHARED.parent, "doofus_paths:CANONICAL_SHARED.parent"),
    ]
    for path, how in candidates:
        if path.exists() and path.is_dir():
            return path, how, {"resolved_path": str(path)}
    return None, "unresolved", {}


def estimate_source_size(root: Path) -> int:
    total = 0
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if any(part in COPY_EXCLUDE_DIRS for part in rel.parts):
            continue
        if p.name in SECRET_EXCLUDE_NAMES:
            continue
        if any(p.name.endswith(s) for s in COPY_EXCLUDE_SUFFIXES):
            continue
        try:
            total += p.stat().st_size
        except OSError:
            pass
    return total


def sqlite_backup(source: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True, timeout=60)
    dst = sqlite3.connect(str(dest), timeout=60)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def run_robocopy(source: Path, dest: Path) -> dict:
    dest.mkdir(parents=True, exist_ok=True)
    xd = " ".join(COPY_EXCLUDE_DIRS)
    xf_names = " ".join(SECRET_EXCLUDE_NAMES)
    cmd = [
        "robocopy",
        str(source),
        str(dest),
        "/E",
        "/COPY:DAT",
        "/R:2",
        "/W:5",
        "/MT:8",
        "/NFL",
        "/NDL",
        "/NJH",
        "/NJS",
        "/XD",
        *COPY_EXCLUDE_DIRS,
        "/XF",
        *SECRET_EXCLUDE_NAMES,
        "*.pyc",
        "*.pyo",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    # robocopy: 0-7 success, >=8 failure
    ok = proc.returncode < 8
    return {"exit_code": proc.returncode, "ok": ok, "stderr_tail": (proc.stderr or "")[-500:]}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def build_checksum_manifest(source: Path, fork: Path, keys: list[str]) -> dict:
    rows = []
    for rel in keys:
        sp = source / rel
        fp = fork / rel
        row = {"path": rel, "source_exists": sp.exists(), "fork_exists": fp.exists()}
        if sp.exists() and fp.exists() and sp.is_file() and fp.is_file():
            sh = sha256_file(sp)
            fh = sha256_file(fp)
            row["source_sha256"] = sh
            row["fork_sha256"] = fh
            row["match"] = sh == fh
        rows.append(row)
    return {"entries": rows, "all_match": all(r.get("match") for r in rows if "match" in r)}


def write_fork_readme(fork: Path, meta: dict) -> None:
    (fork / "README_EXPORT.md").write_text(
        "# Doofus gen1639 Certified Fork Export\n\n"
        f"Exported at: `{meta.get('exported_at')}`\n\n"
        f"Source: `{meta.get('source_root')}`\n\n"
        f"Branch: `{meta.get('branch')}`\n\n"
        f"Commit: `{meta.get('commit')}`\n\n"
        f"Checkpoint: generation `{meta.get('checkpoint_generation')}`, phase `{meta.get('checkpoint_phase')}`\n\n"
        "This is a non-destructive fork copy for independent inspection and continuation.\n\n"
        "See `RESTORE_NOTES.md` and `EXPORT_MANIFEST.json`.\n",
        encoding="utf-8",
    )
    (fork / "RESTORE_NOTES.md").write_text(
        "# Restore Notes\n\n"
        "1. Copy or use this fork directory as `DOOFUS_ROOT`.\n"
        "2. Install venv: `scripts\\doofus_install_local.ps1` or create `.venv_doofus`.\n"
        "3. Set `DOOFUS_ROOT` to this fork path if not using default canonical path.\n"
        "4. Live DB is at `runtime/state/doofus_metrics.sqlite` (stable backup copy).\n"
        "5. Additional backup: `runtime/state/doofus_metrics_gen1639_certified_backup.sqlite`.\n"
        "6. Secrets (`.env`) were excluded from export - configure locally.\n"
        "7. Stop flag should be `stop_requested=true`; do not launch gen1640 without operator approval.\n",
        encoding="utf-8",
    )


def export_fork(*, artifact_dir: Path, timestamp: str | None = None) -> dict:
    artifact_dir = Path(artifact_dir).resolve()
    sys.path.insert(0, str(WORKSPACE))
    from doofus.core import doofus_paths
    from doofus.core.doofus_events import utc_now
    from doofus.supervisor.doofus_crash_recovery import load_checkpoint
    from doofus.supervisor.doofus_cycle_checkpoint import read_checkpoint

    dest_root, resolution_how, resolution_meta = resolve_network_export_dir()
    resolution = {
        "classification": "DOOFUS_NETWORK_EXPORT_DESTINATION_RESOLUTION",
        "chosen_destination_root": str(dest_root) if dest_root else None,
        "resolution_method": resolution_how,
        "resolution_meta": resolution_meta,
        "destination_exists": bool(dest_root and dest_root.exists()),
        "destination_writable": bool(dest_root and os.access(dest_root, os.W_OK)),
        "appears_network_shared": "Shared Folder" in str(dest_root) if dest_root else False,
    }
    if dest_root and dest_root.exists():
        resolution["free_space_bytes"] = shutil.disk_usage(dest_root.drive + "\\").free
    resolution["source_repo_size_estimate_bytes"] = estimate_source_size(WORKSPACE)
    resolution["export_size_estimate_bytes"] = resolution["source_repo_size_estimate_bytes"]
    resolution["full_export_safe"] = bool(
        dest_root
        and dest_root.exists()
        and resolution.get("destination_writable")
        and resolution.get("free_space_bytes", 0) > resolution["export_size_estimate_bytes"] * 1.1
    )
    if not resolution["full_export_safe"]:
        resolution["refusal_reason"] = None if resolution["full_export_safe"] else "destination_unresolved_or_insufficient_space"
    write_pair(artifact_dir, "NETWORK_EXPORT_DESTINATION_RESOLUTION", resolution)

    if not resolution["full_export_safe"]:
        return {"classification": "DOOFUS_NETWORK_FORK_EXPORT_BLOCKED", "resolution": resolution}

    stamp = timestamp or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    fork_name = f"doofus-fork-gen1639-certified-{stamp}"
    fork_path = dest_root / fork_name

    plan = {
        "classification": "DOOFUS_NETWORK_FORK_EXPORT_PLAN",
        "source_repo_root": str(WORKSPACE),
        "destination_root": str(dest_root),
        "fork_folder_name": fork_name,
        "final_fork_path": str(fork_path),
        "copy_method": "robocopy + sqlite backup for live DB",
        "retry_behavior": "robocopy /R:2 /W:5",
        "exclude_dirs": sorted(COPY_EXCLUDE_DIRS),
        "exclude_secrets": sorted(SECRET_EXCLUDE_NAMES),
        "include_git": True,
        "include_runtime_state": True,
        "include_artifacts": True,
        "include_live_db": True,
        "live_db_strategy": "sqlite backup after tree copy",
        "include_db_backups_in_artifacts": True,
        "cache_temp_excluded": True,
        "checksum_strategy": "sha256 on key paths",
        "expected_size_bytes": resolution["export_size_estimate_bytes"],
        "free_space_bytes": resolution.get("free_space_bytes"),
    }
    write_pair(artifact_dir, "NETWORK_FORK_EXPORT_PLAN", plan)

    ck = load_checkpoint()
    cc = read_checkpoint()
    precopy = {
        "classification": "DOOFUS_SOURCE_EXPORT_MANIFEST_PRECOPY",
        "source_branch": subprocess.check_output(["git", "branch", "--show-current"], cwd=WORKSPACE, text=True).strip(),
        "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=WORKSPACE, text=True).strip(),
        "worktree_dirty": bool(subprocess.check_output(["git", "status", "--porcelain=v1"], cwd=WORKSPACE, text=True).strip()),
        "checkpoint": ck,
        "cycle_checkpoint": cc,
        "expected_fork_path": str(fork_path),
        "timestamp": utc_now(),
        "live_db_path": str(doofus_paths.METRICS_DB),
        "artifact_directories_included": ["artifacts/doofus/gen1639-live-verification-v1", str(artifact_dir.relative_to(WORKSPACE))],
        "paths_excluded": sorted(SECRET_EXCLUDE_NAMES | COPY_EXCLUDE_DIRS),
    }
    write_pair(artifact_dir, "SOURCE_EXPORT_MANIFEST_PRECOPY", precopy)

    if fork_path.exists():
        shutil.rmtree(fork_path, ignore_errors=True)

    copy_result = run_robocopy(WORKSPACE, fork_path)
    db_backup_path = fork_path / "runtime" / "state" / "doofus_metrics_gen1639_certified_backup.sqlite"
    live_db_dest = fork_path / "runtime" / "state" / "doofus_metrics.sqlite"
    db_error = None
    try:
        sqlite_backup(doofus_paths.METRICS_DB, live_db_dest)
        sqlite_backup(doofus_paths.METRICS_DB, db_backup_path)
        db_included = True
    except Exception as exc:  # noqa: BLE001
        db_included = live_db_dest.exists()
        db_error = str(exc)

    export_manifest = {
        "classification": "DOOFUS_EXPORT_MANIFEST",
        "exported_at": utc_now(),
        "source_root": str(WORKSPACE),
        "fork_path": str(fork_path),
        "branch": precopy["source_branch"],
        "commit": precopy["source_commit"],
        "checkpoint": ck,
        "cycle_checkpoint": cc,
        "included": {
            "git": (fork_path / ".git").exists(),
            "runtime_state": (fork_path / "runtime" / "state").exists(),
            "artifacts": (fork_path / "artifacts").exists(),
            "gen1639_live_artifacts": (fork_path / "artifacts" / "doofus" / "gen1639-live-verification-v1").exists(),
            "live_db": live_db_dest.exists(),
            "live_db_backup": db_backup_path.exists(),
        },
        "excluded_secrets": sorted(SECRET_EXCLUDE_NAMES),
        "excluded_dirs": sorted(COPY_EXCLUDE_DIRS),
        "robocopy": copy_result,
        "live_db_backup_error": db_error,
    }
    write_pair(fork_path, "EXPORT_MANIFEST", export_manifest)
    write_pair(fork_path, "EXPORT_MANIFEST", export_manifest)  # json+md via write_pair

    key_paths = [
        "doofus/supervisor/provider_aware_live_cycle.py",
        "runtime/state/last_checkpoint.json",
        "runtime/state/cycle_checkpoint.json",
        "artifacts/doofus/gen1639-live-verification-v1/FINAL_REPORT.json",
    ]
    checksums = build_checksum_manifest(WORKSPACE, fork_path, key_paths)
    checksum_lines = [f"{e['fork_sha256']}  {e['path']}" for e in checksums["entries"] if e.get("fork_sha256")]
    (fork_path / "CHECKSUMS.sha256").write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")

    meta = {
        "exported_at": utc_now(),
        "source_root": str(WORKSPACE),
        "branch": precopy["source_branch"],
        "commit": precopy["source_commit"],
        "checkpoint_generation": ck.get("generation"),
        "checkpoint_phase": ck.get("phase"),
    }
    write_fork_readme(fork_path, meta)

    fork_commit = None
    if (fork_path / ".git").exists():
        try:
            fork_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=fork_path, text=True).strip()
        except subprocess.CalledProcessError:
            fork_commit = None

    verification = {
        "classification": "DOOFUS_EXPORT_VERIFICATION",
        "fork_path_exists": fork_path.exists(),
        "git_exists": (fork_path / ".git").exists(),
        "fork_commit": fork_commit,
        "source_commit_match": fork_commit == precopy["source_commit"],
        "doofus_package_exists": (fork_path / "doofus").is_dir(),
        "tests_exists": (fork_path / "tests").is_dir(),
        "scripts_exists": (fork_path / "scripts").is_dir(),
        "runtime_state_exists": (fork_path / "runtime" / "state").is_dir(),
        "gen1639_artifacts_exist": (fork_path / "artifacts" / "doofus" / "gen1639-live-verification-v1").is_dir(),
        "live_db_exists": live_db_dest.exists(),
        "live_db_backup_exists": db_backup_path.exists(),
        "export_manifest_exists": (fork_path / "EXPORT_MANIFEST.json").exists(),
        "checksum_manifest_exists": (fork_path / "CHECKSUMS.sha256").exists(),
        "checksums": checksums,
        "robocopy_ok": copy_result.get("ok"),
        "source_checkpoint_unchanged": load_checkpoint() == ck,
    }
    write_pair(fork_path, "EXPORT_VERIFICATION", verification)
    write_pair(artifact_dir, "NETWORK_FORK_EXPORT_RESULT", {
        "classification": "DOOFUS_NETWORK_FORK_EXPORT_RESULT",
        "fork_path": str(fork_path),
        "robocopy": copy_result,
        "live_db_included": db_included,
        "live_db_backup_error": db_error,
        "verification_summary": {k: verification[k] for k in ("fork_path_exists", "git_exists", "fork_commit", "checksums", "robocopy_ok")},
    })
    return {
        "classification": "DOOFUS_NETWORK_FORK_EXPORT_COMPLETE",
        "fork_path": str(fork_path),
        "verification": verification,
        "resolution": resolution,
    }


def main() -> int:
    artifact_dir = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else (WORKSPACE / "artifacts" / "doofus" / "gen1639-postlive-certification-network-fork-v1").resolve()
    result = export_fork(artifact_dir=artifact_dir)
    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("classification") == "DOOFUS_NETWORK_FORK_EXPORT_COMPLETE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
