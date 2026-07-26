"""Fork Doofus source snapshot to Desktop Shared Folder."""
from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from doofus.core.doofus_paths import ROOT, SHARED
from doofus.reports.doofus_shared_folder_exporter import export_shared_folder

FORK_ROOT = SHARED.parent / "Doofus-Source"
IGNORE_NAMES = {
    ".venv_doofus",
    ".pytest_cache",
    "__pycache__",
    ".git",
    "doofus.egg-info",
    ".env",
}
IGNORE_SUFFIXES = {".pyc", ".pyo", ".sqlite", ".sqlite-wal", ".sqlite-shm"}
IGNORE_RUNTIME_GLOBS = ("*.sqlite", "*.sqlite-wal", "*.sqlite-shm")


def _ignore(dirpath: str, names: list[str]) -> set[str]:
    out: set[str] = set()
    rel = dirpath.replace(str(ROOT), "").replace("\\", "/")
    for name in names:
        if name in IGNORE_NAMES:
            out.add(name)
        elif any(name.endswith(s) for s in IGNORE_SUFFIXES):
            out.add(name)
        elif "/runtime/logs" in rel or rel.endswith("/runtime/logs"):
            if name.endswith(".log"):
                out.add(name)
    return out


def _prune_runtime_logs(dest: Path) -> None:
    logs = dest / "runtime" / "logs"
    if not logs.is_dir():
        return
    for p in logs.glob("*.log"):
        try:
            if p.stat().st_size > 512_000:
                p.write_text(f"# truncated on fork at {datetime.now(timezone.utc).isoformat()}\n", encoding="utf-8")
        except OSError:
            pass


def _prune_old_snapshots(dest: Path, *, keep: int = 2) -> None:
    snapshots = sorted(dest.glob("snapshot-*"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in snapshots[keep:]:
        shutil.rmtree(old, ignore_errors=True)


def fork_to_shared(*, target: Path | None = None) -> dict:
    dest = target or FORK_ROOT
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    snapshot = dest / f"snapshot-{stamp}"
    if dest.exists() and any(dest.iterdir()):
        latest_link = dest / "latest"
        if latest_link.is_symlink() or latest_link.exists():
            try:
                if latest_link.is_symlink() or latest_link.is_file():
                    latest_link.unlink(missing_ok=True)
                elif latest_link.is_dir():
                    shutil.rmtree(latest_link, ignore_errors=True)
            except OSError:
                pass
    if snapshot.exists():
        shutil.rmtree(snapshot, ignore_errors=True)
    shutil.copytree(ROOT, snapshot, ignore=_ignore, dirs_exist_ok=False)
    _prune_runtime_logs(snapshot)
    manifest = {
        "classification": "DOOFUS_SOURCE_FORK",
        "forked_at": datetime.now(timezone.utc).isoformat(),
        "source": str(ROOT),
        "destination": str(snapshot),
        "shared_reports": str(SHARED),
    }
    (snapshot / "FORK_MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    dest.mkdir(parents=True, exist_ok=True)
    latest = dest / "latest"
    try:
        if latest.exists() or latest.is_symlink():
            latest.unlink(missing_ok=True)
        latest.symlink_to(snapshot, target_is_directory=True)
    except OSError:
        latest = dest / "LATEST_SNAPSHOT.txt"
        latest.write_text(str(snapshot), encoding="utf-8")
    export = export_shared_folder()
    manifest["shared_export"] = export.get("classification")
    _prune_old_snapshots(dest, keep=2)
    (SHARED / "DOOFUS-SOURCE-FORK-MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (SHARED / "DOOFUS-SOURCE-FORK-README.md").write_text(
        "# Doofus Source Fork\n\n"
        f"Latest snapshot: `{snapshot}`\n\n"
        f"Forked from: `{ROOT}`\n\n"
        "Reports in this folder are refreshed on each fork.\n\n"
        "## Quick start (from snapshot)\n\n"
        "```powershell\n"
        "cd latest\n"
        "scripts\\doofus_install_local.ps1\n"
        "scripts\\doofus_runtime_heal.py\n"
        "scripts\\doofus_start.ps1\n"
        "```\n",
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    result = fork_to_shared(target=target)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
