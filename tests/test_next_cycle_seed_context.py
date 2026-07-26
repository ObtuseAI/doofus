"""Tests for seed context builder."""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

from doofus.evolution.seed_context_builder import build_seed_context


def test_seed_context_deterministic_shape():
    with patch("doofus.evolution.seed_context_builder.analyze_generations", return_value={"aggregate_dominant_rejection_reason": "proof_density_gate", "zero_promotion_pattern": True, "aggregate_rejection_histogram": {}}):
        with patch("doofus.evolution.seed_context_builder.handoff_report", return_value={"queue_summary": {"pending": 3}}):
            with patch("doofus.evolution.seed_context_builder.build_next_cycle_seed_context_plan", return_value={"decision": "staged_as_artifact_only_context"}):
                with patch("sqlite3.connect") as mock_conn:
                    mock_conn.return_value.execute.return_value.fetchone.return_value = ("c1", 0.8)
                    payload = build_seed_context(certified_generation=1643, next_generation=1644)
    assert payload["classification"] == "DOOFUS_NEXT_CYCLE_SEED_CONTEXT"
    assert payload["runtime_injection"] is False
    assert payload["best_near_miss_candidate"] == "c1"
