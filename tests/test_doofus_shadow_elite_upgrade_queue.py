"""Tests for shadow elite upgrade queue."""
from doofus.evolution.shadow_elite_upgrade_queue import queue_summary


def test_queue_summary_shape():
    q = queue_summary()
    assert "upgrades" in q
    assert "pending_upgrades" in q
