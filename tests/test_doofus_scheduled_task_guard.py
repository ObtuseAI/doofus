"""Tests for scheduled task guard."""
from doofus.supervisor.scheduled_task_guard import get_scheduled_task_states


def test_task_states_shape():
    states = get_scheduled_task_states()
    assert "supervisor_state" in states
    assert "dashboard_state" in states
    assert "watchdog_registered" in states
