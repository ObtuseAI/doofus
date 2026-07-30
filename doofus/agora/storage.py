"""Append-only SQLite ledger and content-addressed artifact vault."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from doofus.agora.contracts import IdeaCard, ProviderOutcome, TermsDecision
from doofus.agora.errors import ArtifactIntegrityError
from doofus.core.doofus_events import utc_now

SCHEMA = """
CREATE TABLE IF NOT EXISTS agora_events (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    mission_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    previous_hash TEXT NOT NULL,
    event_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_agora_events_mission_sequence
    ON agora_events(mission_id, sequence);
CREATE INDEX IF NOT EXISTS idx_agora_events_type_sequence
    ON agora_events(event_type, sequence);
CREATE TABLE IF NOT EXISTS agora_artifacts (
    sha256 TEXT PRIMARY KEY,
    artifact_kind TEXT NOT NULL,
    relative_path TEXT NOT NULL UNIQUE,
    byte_length INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agora_terms_reviews (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_id TEXT NOT NULL,
    decision_json TEXT NOT NULL,
    document_sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_agora_terms_provider_sequence
    ON agora_terms_reviews(provider_id, sequence);
CREATE TABLE IF NOT EXISTS agora_provider_outcomes (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_id TEXT NOT NULL,
    mission_type TEXT NOT NULL,
    role_id TEXT NOT NULL,
    topology_id TEXT NOT NULL,
    reward REAL NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_agora_outcomes_context
    ON agora_provider_outcomes(provider_id, mission_type, role_id, topology_id);
CREATE TABLE IF NOT EXISTS agora_quality_archive (
    niche_key TEXT PRIMARY KEY,
    idea_id TEXT NOT NULL,
    mission_id TEXT NOT NULL,
    score REAL NOT NULL,
    payload_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_agora_quality_archive_score
    ON agora_quality_archive(score DESC);
"""


def canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


class AgoraRepository:
    """Connector for the isolated append-only Agora persistence boundary."""

    def __init__(self, database_path: Path, vault_root: Path) -> None:
        self._database_path = database_path
        self._vault_root = vault_root

    @property
    def database_path(self) -> Path:
        return self._database_path

    @property
    def vault_root(self) -> Path:
        return self._vault_root

    def initialize(self) -> None:
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        self._vault_root.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def append_event(self, mission_id: str, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.initialize()
        payload_json = canonical_json(payload)
        created_at = utc_now()
        event_id = f"EVT_{uuid.uuid4().hex}"
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            previous_row = connection.execute(
                "SELECT event_hash FROM agora_events ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            previous_hash = str(previous_row["event_hash"]) if previous_row else "0" * 64
            event_material = canonical_json(
                {
                    "event_id": event_id,
                    "mission_id": mission_id,
                    "event_type": event_type,
                    "payload_json": payload_json,
                    "previous_hash": previous_hash,
                    "created_at": created_at,
                }
            ).encode("utf-8")
            event_hash = sha256_bytes(event_material)
            connection.execute(
                """INSERT INTO agora_events
                   (event_id, mission_id, event_type, payload_json, previous_hash, event_hash, created_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (event_id, mission_id, event_type, payload_json, previous_hash, event_hash, created_at),
            )
        return {
            "event_id": event_id,
            "mission_id": mission_id,
            "event_type": event_type,
            "payload": payload,
            "previous_hash": previous_hash,
            "event_hash": event_hash,
            "created_at": created_at,
        }

    def mission_events(self, mission_id: str) -> list[dict[str, Any]]:
        self.initialize()
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT sequence, event_id, mission_id, event_type, payload_json,
                          previous_hash, event_hash, created_at
                   FROM agora_events WHERE mission_id=? ORDER BY sequence""",
                (mission_id,),
            ).fetchall()
        return [
            {
                "sequence": int(row["sequence"]),
                "event_id": str(row["event_id"]),
                "mission_id": str(row["mission_id"]),
                "event_type": str(row["event_type"]),
                "payload": json.loads(str(row["payload_json"])),
                "previous_hash": str(row["previous_hash"]),
                "event_hash": str(row["event_hash"]),
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]

    def all_events(self, limit: int) -> list[dict[str, Any]]:
        self.initialize()
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT sequence, event_id, mission_id, event_type, payload_json,
                          previous_hash, event_hash, created_at
                   FROM agora_events ORDER BY sequence DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [
            {
                "sequence": int(row["sequence"]),
                "event_id": str(row["event_id"]),
                "mission_id": str(row["mission_id"]),
                "event_type": str(row["event_type"]),
                "payload": json.loads(str(row["payload_json"])),
                "previous_hash": str(row["previous_hash"]),
                "event_hash": str(row["event_hash"]),
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]

    def verify_event_chain(self) -> dict[str, Any]:
        self.initialize()
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT event_id, mission_id, event_type, payload_json,
                          previous_hash, event_hash, created_at
                   FROM agora_events ORDER BY sequence"""
            ).fetchall()
        previous_hash = "0" * 64
        for index, row in enumerate(rows):
            if str(row["previous_hash"]) != previous_hash:
                raise ArtifactIntegrityError(f"Agora event chain previous_hash mismatch at sequence {index + 1}")
            material = canonical_json(
                {
                    "event_id": str(row["event_id"]),
                    "mission_id": str(row["mission_id"]),
                    "event_type": str(row["event_type"]),
                    "payload_json": str(row["payload_json"]),
                    "previous_hash": str(row["previous_hash"]),
                    "created_at": str(row["created_at"]),
                }
            ).encode("utf-8")
            expected_hash = sha256_bytes(material)
            if expected_hash != str(row["event_hash"]):
                raise ArtifactIntegrityError(f"Agora event chain hash mismatch at sequence {index + 1}")
            previous_hash = expected_hash
        return {"valid": True, "event_count": len(rows), "head_hash": previous_hash}

    def store_blob(self, artifact_kind: str, payload: bytes) -> tuple[str, Path]:
        self.initialize()
        digest = sha256_bytes(payload)
        relative_path = Path("sha256") / digest[:2] / digest
        destination = self._vault_root / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            with destination.open("xb") as artifact_file:
                artifact_file.write(payload)
                artifact_file.flush()
                os.fsync(artifact_file.fileno())
        except FileExistsError:
            existing = destination.read_bytes()
            if existing != payload:
                raise ArtifactIntegrityError(f"content-addressed artifact conflict: {destination}")
        with self._connect() as connection:
            connection.execute(
                """INSERT OR IGNORE INTO agora_artifacts
                   (sha256, artifact_kind, relative_path, byte_length, created_at)
                   VALUES (?,?,?,?,?)""",
                (digest, artifact_kind, str(relative_path), len(payload), utc_now()),
            )
        return digest, destination

    def read_blob(self, digest: str) -> bytes:
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest.lower()):
            raise ArtifactIntegrityError(f"invalid artifact digest: {digest}")
        path = self._vault_root / "sha256" / digest[:2] / digest
        if not path.is_file():
            raise ArtifactIntegrityError(f"content-addressed artifact missing: {digest}")
        payload = path.read_bytes()
        if sha256_bytes(payload) != digest:
            raise ArtifactIntegrityError(f"content-addressed artifact hash mismatch: {digest}")
        return payload

    def record_terms_decision(self, decision: TermsDecision) -> None:
        self.initialize()
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO agora_terms_reviews
                   (provider_id, decision_json, document_sha256, created_at)
                   VALUES (?,?,?,?)""",
                (
                    decision.provider_id,
                    canonical_json(decision.model_dump(mode="json")),
                    decision.document_sha256,
                    decision.reviewed_at,
                ),
            )

    def latest_terms_decision(self, provider_id: str) -> TermsDecision | None:
        self.initialize()
        with self._connect() as connection:
            row = connection.execute(
                """SELECT decision_json FROM agora_terms_reviews
                   WHERE provider_id=? ORDER BY sequence DESC LIMIT 1""",
                (provider_id,),
            ).fetchone()
        return TermsDecision.model_validate_json(str(row["decision_json"])) if row else None

    def record_provider_outcome(self, outcome: ProviderOutcome) -> None:
        self.initialize()
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO agora_provider_outcomes
                   (provider_id, mission_type, role_id, topology_id, reward, payload_json, created_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (
                    outcome.provider_id,
                    outcome.mission_type,
                    outcome.role_id,
                    outcome.topology_id,
                    outcome.reward,
                    canonical_json(outcome.model_dump(mode="json")),
                    outcome.created_at,
                ),
            )

    def provider_profile(
        self,
        provider_id: str,
        mission_type: str,
        role_id: str,
        topology_id: str,
    ) -> dict[str, float]:
        self.initialize()
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT reward, payload_json FROM agora_provider_outcomes
                   WHERE provider_id=? AND mission_type=? AND role_id=? AND topology_id=?""",
                (provider_id, mission_type, role_id, topology_id),
            ).fetchall()
        rewards = [float(row["reward"]) for row in rows]
        successes = sum(rewards)
        failures = sum(1.0 - reward for reward in rewards)
        return {
            "alpha": 1.0 + successes,
            "beta": 1.0 + failures,
            "trials": float(len(rewards)),
            "mean_reward": sum(rewards) / len(rewards) if rewards else 0.5,
        }

    def topology_profile(self, mission_type: str, topology_id: str) -> dict[str, float]:
        self.initialize()
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT reward FROM agora_provider_outcomes
                   WHERE mission_type=? AND topology_id=?""",
                (mission_type, topology_id),
            ).fetchall()
        rewards = [float(row["reward"]) for row in rows]
        return {
            "alpha": 1.0 + sum(rewards),
            "beta": 1.0 + sum(1.0 - reward for reward in rewards),
            "trials": float(len(rewards)),
        }

    def upsert_quality_archive(
        self,
        niche_key: str,
        card: IdeaCard,
        score: float,
    ) -> dict[str, Any]:
        self.initialize()
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO agora_quality_archive
                   (niche_key, idea_id, mission_id, score, payload_json, updated_at)
                   VALUES (?,?,?,?,?,?)
                   ON CONFLICT(niche_key) DO UPDATE SET
                     idea_id=excluded.idea_id,
                     mission_id=excluded.mission_id,
                     score=excluded.score,
                     payload_json=excluded.payload_json,
                     updated_at=excluded.updated_at
                   WHERE excluded.score > agora_quality_archive.score""",
                (
                    niche_key,
                    card.idea_id,
                    card.mission_id,
                    score,
                    canonical_json(card.model_dump(mode="json")),
                    utc_now(),
                ),
            )
            row = connection.execute(
                """SELECT idea_id, mission_id, score, updated_at
                   FROM agora_quality_archive WHERE niche_key=?""",
                (niche_key,),
            ).fetchone()
        if row is None:
            raise ArtifactIntegrityError(
                f"Agora quality archive insert did not produce a row: {niche_key}"
            )
        return {
            "niche_key": niche_key,
            "idea_id": str(row["idea_id"]),
            "mission_id": str(row["mission_id"]),
            "score": float(row["score"]),
            "updated_at": str(row["updated_at"]),
        }

    def quality_archive_snapshot(self, limit: int) -> dict[str, Any]:
        self.initialize()
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT niche_key, idea_id, mission_id, score, updated_at
                   FROM agora_quality_archive
                   ORDER BY score DESC, niche_key LIMIT ?""",
                (limit,),
            ).fetchall()
            count_row = connection.execute(
                "SELECT COUNT(*) AS count FROM agora_quality_archive"
            ).fetchone()
        return {
            "cell_count": int(count_row["count"]) if count_row else 0,
            "top_cells": [
                {
                    "niche_key": str(row["niche_key"]),
                    "idea_id": str(row["idea_id"]),
                    "mission_id": str(row["mission_id"]),
                    "score": float(row["score"]),
                    "updated_at": str(row["updated_at"]),
                }
                for row in rows
            ],
        }
