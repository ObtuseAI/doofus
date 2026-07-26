"""Tests for promotion near-miss analysis."""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

from doofus.evaluation.promotion_near_miss import find_near_misses


def _seed_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE candidates (
            candidate_id TEXT PRIMARY KEY, parent_id TEXT, generation INTEGER, status TEXT,
            score_total REAL, rejection_reason TEXT, promotion_status TEXT, traits TEXT, mutation_type TEXT
        );
        """
    )
    conn.execute(
        "INSERT INTO candidates VALUES (?,?,?,?,?,?,?,?,?)",
        ("near_miss_1", "p", 1642, "rejected", 0.75, "proof_density_gate", "none", "{}", "mut"),
    )
    conn.commit()
    conn.close()


def test_find_near_misses_with_mocked_miner():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "metrics.sqlite"
        _seed_db(db)
        miner_payload = {
            "closest_to_promotion_top_25": [
                {
                    "candidate_id": "near_miss_1",
                    "score_total": 0.75,
                    "rejection_reason": "proof_density_gate",
                    "generation": 1642,
                }
            ],
            "proof_density_blocked_top_50": [{"candidate_id": "near_miss_1"}],
            "decision": "MINER_OK",
        }
        with patch("doofus.evaluation.promotion_near_miss.mine_high_score_rejections", return_value=miner_payload):
            report = find_near_misses(1642, db_path=db)
        assert report["classification"] == "DOOFUS_PROMOTION_NEAR_MISS_REPORT"
        assert report["near_miss_count"] >= 1
        assert report["best_near_miss_candidate"] == "near_miss_1"
