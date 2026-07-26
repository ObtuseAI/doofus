"""Tests for Doofus generation summary builder."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

WORKSPACE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE))

from scripts.doofus_generation_summary import build_generation_summary, write_pair
from doofus.supervisor.doofus_crash_recovery import load_checkpoint


def test_generation_summary_reads_gen1639():
    summary = build_generation_summary(1639)
    assert summary["generation"] == 1639
    assert summary["live_route_invoked"] is False
    assert "db_generation_counts" in summary


def test_generation_summary_handles_missing_telemetry():
    summary = build_generation_summary(9999)
    assert summary["inline_rescue"]["event_count"] == 0


def test_generation_summary_writes_files(tmp_path: Path):
    summary = build_generation_summary(1639)
    write_pair(tmp_path, "generation_1639_summary", summary)
    assert (tmp_path / "generation_1639_summary.json").exists()
    assert (tmp_path / "generation_1639_summary.md").exists()


def test_no_checkpoint_mutation():
    before = load_checkpoint()
    build_generation_summary(1639)
    assert load_checkpoint() == before
