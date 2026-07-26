"""Shared SQLite connection helpers for Doofus metrics DB."""

from __future__ import annotations



import sqlite3

import os

import time

from contextlib import contextmanager

from pathlib import Path

from typing import Iterator



from doofus.core import doofus_paths



DEFAULT_TIMEOUT = 30.0





def metrics_db_path() -> Path:

    return doofus_paths.METRICS_DB


def _assert_metrics_path_allowed(path: Path) -> None:
    if (
        os.environ.get("PYTEST_CURRENT_TEST")
        and os.environ.get("DOOFUS_ALLOW_LIVE_RUNTIME_TESTS", "0") != "1"
        and path.resolve() == doofus_paths.CANONICAL_METRICS_DB.resolve()
    ):
        raise RuntimeError(f"pytest attempted to open live metrics DB: {path}")





def _log_contention(*, event_type: str, retries: int, latency_ms: float, detail: str = "") -> None:

    """Best-effort contention log — direct connect to avoid retry recursion."""

    try:

        from doofus.core.doofus_events import utc_now

        from doofus.core.doofus_state import init_db



        init_db()

        path = metrics_db_path()

        conn = sqlite3.connect(path, timeout=1.0)

        conn.execute(

            "INSERT INTO db_health_events (event_type, retries, latency_ms, detail, created_at) VALUES (?,?,?,?,?)",

            (event_type, retries, latency_ms, detail[:500], utc_now()),

        )

        conn.commit()

        conn.close()

    except Exception:

        pass





def connect_metrics_db(*, db_path: Path | None = None, timeout: float = DEFAULT_TIMEOUT) -> sqlite3.Connection:

    doofus_paths.STATE.mkdir(parents=True, exist_ok=True)

    path = db_path or metrics_db_path()
    _assert_metrics_path_allowed(path)

    last_exc: Exception | None = None

    started = time.perf_counter()

    retries = 0

    for attempt in range(5):

        try:

            conn = sqlite3.connect(path, timeout=timeout)

            conn.execute(f"PRAGMA busy_timeout={int(timeout * 1000)}")

            try:

                conn.execute("PRAGMA journal_mode=WAL")

            except sqlite3.OperationalError:

                pass

            elapsed_ms = (time.perf_counter() - started) * 1000.0

            if retries > 0 or elapsed_ms > 500:

                _log_contention(

                    event_type="connect_retry" if retries else "connect_slow",

                    retries=retries,

                    latency_ms=round(elapsed_ms, 2),

                    detail=f"attempts={attempt + 1}",

                )

            return conn

        except sqlite3.OperationalError as exc:

            last_exc = exc

            retries += 1

            time.sleep(0.5)

    elapsed_ms = (time.perf_counter() - started) * 1000.0

    _log_contention(

        event_type="connect_locked",

        retries=retries,

        latency_ms=round(elapsed_ms, 2),

        detail=str(last_exc or "database is locked")[:200],

    )

    raise last_exc or sqlite3.OperationalError("database is locked")





@contextmanager

def metrics_conn(*, db_path: Path | None = None, timeout: float = DEFAULT_TIMEOUT) -> Iterator[sqlite3.Connection]:

    """Ensure schema exists, yield a connection, commit on success."""

    from doofus.core.doofus_state import init_db



    init_db(db_path)

    conn = connect_metrics_db(db_path=db_path, timeout=timeout)

    try:

        yield conn

        conn.commit()

    finally:

        conn.close()
