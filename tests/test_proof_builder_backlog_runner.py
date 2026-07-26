"""Tests for proof-builder backlog runner."""
from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

WORKSPACE = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "doofus_proof_builder_backlog_runner",
    WORKSPACE / "scripts" / "doofus_proof_builder_backlog_runner.py",
)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["doofus_proof_builder_backlog_runner"] = _mod
assert _spec.loader is not None
_spec.loader.exec_module(_mod)
run_backlog = _mod.run_backlog


def test_backlog_dry_run_safe():
    with tempfile.TemporaryDirectory() as tmp:
        queue = {"pending": 2, "queue_size": 2, "enabled": True, "outcomes": {}}
    with patch("doofus.proof.proof_builder_queue.queue_summary", return_value=queue):
        with patch("doofus.proof.proof_builder_queue.pending_entries", return_value=[{"candidate_id": "c1"}]):
                payload = run_backlog(dry_run=True, output_dir=Path(tmp), item_budget=1, time_budget_seconds=30)
        assert payload["dry_run"] is True
        assert payload["live_route_invoked"] is False
        assert payload["db_mutation"] is False
