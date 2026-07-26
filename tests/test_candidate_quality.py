"""Tests for candidate quality diagnostics."""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from doofus.evaluation.candidate_quality import analyze_generation, analyze_generations


def _seed_db(path: Path, generation: int, *, count: int = 24, create: bool = True) -> None:
    conn = sqlite3.connect(path)
    if create:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS candidates (
                candidate_id TEXT PRIMARY KEY, parent_id TEXT, generation INTEGER, status TEXT,
                score_total REAL, rejection_reason TEXT, promotion_status TEXT, traits TEXT, mutation_type TEXT
            );
            """
        )
    for i in range(count):
        conn.execute(
            "INSERT INTO candidates VALUES (?,?,?,?,?,?,?,?,?)",
            (
                f"g{generation}_{i}",
                "p",
                generation,
                "rejected",
                0.65,
                "proof_density_gate",
                "none",
                "{}",
                "mut",
            ),
        )
    conn.commit()
    conn.close()


def test_analyze_generation_histogram():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "metrics.sqlite"
        _seed_db(db, 1642)
        conn = sqlite3.connect(db)
        summary = analyze_generation(conn, 1642)
        conn.close()
        assert summary["candidate_count"] == 24
        assert summary["promoted"] == 0
        assert summary["dominant_rejection_reason"] == "proof_density_gate"


def test_analyze_generations_zero_promotion_pattern():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "metrics.sqlite"
        _seed_db(db, 1641, create=True)
        _seed_db(db, 1642, create=False)
        payload = analyze_generations(start_generation=1641, end_generation=1642, db_path=db)
        assert payload["classification"] == "DOOFUS_CANDIDATE_QUALITY_REPORT"
        assert payload["zero_promotion_pattern"] is True
        assert payload["aggregate_dominant_rejection_reason"] == "proof_density_gate"
