from __future__ import annotations

import sqlite3

from doofus.runtime.metrics_failover import database_health, promote_replica, replicate_metrics_db


def test_replication_and_explicit_failover(tmp_path) -> None:
    primary = tmp_path / "primary.sqlite"
    replica = tmp_path / "remote" / "replica.sqlite"
    conn = sqlite3.connect(primary)
    try:
        conn.execute("CREATE TABLE evidence (value TEXT NOT NULL)")
        conn.execute("INSERT INTO evidence VALUES ('verified')")
        conn.commit()
    finally:
        conn.close()

    copied = replicate_metrics_db(source=primary, replica=replica)
    assert copied["classification"] == "METRICS_REPLICATION_COMPLETE"
    assert database_health(replica)["healthy"] is True
    assert replica.with_suffix(".sqlite.manifest.json").is_file()

    primary.unlink()
    blocked = promote_replica(primary=primary, replica=replica)
    assert blocked == {"classification": "METRICS_FAILOVER_BLOCKED", "reason": "authorization_required"}
    promoted = promote_replica(primary=primary, replica=replica, authorize=True)
    assert promoted["classification"] == "METRICS_FAILOVER_COMPLETE"
    conn = sqlite3.connect(primary)
    try:
        assert conn.execute("SELECT value FROM evidence").fetchone()[0] == "verified"
    finally:
        conn.close()


def test_failover_refuses_to_replace_healthy_primary(tmp_path) -> None:
    primary = tmp_path / "primary.sqlite"
    replica = tmp_path / "replica.sqlite"
    for path in (primary, replica):
        conn = sqlite3.connect(path)
        try:
            conn.execute("CREATE TABLE sample (id INTEGER)")
            conn.commit()
        finally:
            conn.close()
    result = promote_replica(primary=primary, replica=replica, authorize=True)
    assert result["reason"] == "primary_healthy"
