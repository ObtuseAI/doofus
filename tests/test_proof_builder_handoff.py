"""Tests for proof-builder handoff reporting."""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

from doofus.reports.proof_builder_handoff_report import handoff_report


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
        ("q1", "p", 1642, "rejected", 0.8, "proof_density_gate|_queued_for_proof_builder", "none", "{}", "mut"),
    )
    conn.commit()
    conn.close()


def test_handoff_report_extracts_queue_summary():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "metrics.sqlite"
        _seed_db(db)
        queue = {
            "enabled": True,
            "queue_size": 1,
            "pending": 1,
            "by_generation": {"1642": 1},
            "outcomes": {"pending": 1},
        }
        with patch("doofus.reports.proof_builder_handoff_report.queue_summary", return_value=queue):
            with patch("doofus.reports.proof_builder_handoff_report.read_jsonl", return_value=[]):
                with patch("doofus.reports.proof_builder_handoff_report.METRICS_DB", db):
                    report = handoff_report(generation=1642)
        assert report["classification"] == "DOOFUS_PROOF_BUILDER_HANDOFF_REPORT"
        assert report["candidates_queued_for_proof_builder_in_db"] == 1
        assert report["handoff_status"] == "measured"
