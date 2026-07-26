"""SQLite snapshot replication and explicit failover for a second machine.

Replication uses SQLite's online backup API, never a raw copy of a live WAL
database.  Promotion is fail-closed: callers must explicitly authorize it and
the primary must be missing or fail ``PRAGMA quick_check``.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

from doofus.core.doofus_events import utc_now
from doofus.core.doofus_paths import METRICS_DB


def configured_replica_path() -> Path | None:
    raw = os.environ.get("DOOFUS_METRICS_REPLICA", "").strip()
    return Path(raw) if raw else None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def database_health(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"healthy": False, "reason": "missing", "path": str(path)}
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5.0)
        row = conn.execute("PRAGMA quick_check").fetchone()
        healthy = bool(row and row[0] == "ok")
        return {"healthy": healthy, "reason": "ok" if healthy else str(row[0]), "path": str(path)}
    except sqlite3.Error as exc:
        return {"healthy": False, "reason": type(exc).__name__, "path": str(path)}
    finally:
        if conn is not None:
            conn.close()


def _online_backup(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.unlink(missing_ok=True)
    try:
        src = sqlite3.connect(f"file:{source}?mode=ro", uri=True, timeout=30.0)
        dst = sqlite3.connect(temporary, timeout=30.0)
        try:
            src.backup(dst)
            dst.commit()
        finally:
            dst.close()
            src.close()
        health = database_health(temporary)
        if not health["healthy"]:
            raise RuntimeError(f"replica verification failed: {health['reason']}")
        last_error: PermissionError | None = None
        for _ in range(20):
            try:
                os.replace(temporary, destination)
                last_error = None
                break
            except PermissionError as exc:
                last_error = exc
                time.sleep(0.05)
        if last_error is not None:
            raise last_error
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except PermissionError:
            pass


def replicate_metrics_db(*, source: Path | None = None, replica: Path | None = None) -> dict[str, Any]:
    source = source or METRICS_DB
    replica = replica or configured_replica_path()
    if replica is None:
        return {"classification": "METRICS_REPLICATION_SKIPPED", "reason": "replica_not_configured"}
    if source.resolve() == replica.resolve():
        raise ValueError("primary and replica paths must differ")
    health = database_health(source)
    if not health["healthy"]:
        return {"classification": "METRICS_REPLICATION_BLOCKED", "primary": health}
    _online_backup(source, replica)
    result = {
        "classification": "METRICS_REPLICATION_COMPLETE",
        "replicated_at": utc_now(),
        "primary": str(source),
        "replica": str(replica),
        "sha256": _sha256(replica),
        "bytes": replica.stat().st_size,
        "replica_health": database_health(replica),
    }
    manifest = replica.with_suffix(replica.suffix + ".manifest.json")
    manifest.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def promote_replica(
    *,
    primary: Path | None = None,
    replica: Path | None = None,
    authorize: bool = False,
) -> dict[str, Any]:
    primary = primary or METRICS_DB
    replica = replica or configured_replica_path()
    if not authorize:
        return {"classification": "METRICS_FAILOVER_BLOCKED", "reason": "authorization_required"}
    if replica is None:
        return {"classification": "METRICS_FAILOVER_BLOCKED", "reason": "replica_not_configured"}
    primary_health = database_health(primary)
    if primary_health["healthy"]:
        return {"classification": "METRICS_FAILOVER_BLOCKED", "reason": "primary_healthy"}
    replica_health = database_health(replica)
    if not replica_health["healthy"]:
        return {"classification": "METRICS_FAILOVER_BLOCKED", "reason": "replica_unhealthy"}
    _online_backup(replica, primary)
    return {
        "classification": "METRICS_FAILOVER_COMPLETE",
        "promoted_at": utc_now(),
        "primary": str(primary),
        "replica": str(replica),
        "sha256": _sha256(primary),
        "primary_health": database_health(primary),
    }
