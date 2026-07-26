"""Tests for OpenRouter DeepSeek provider route."""
from __future__ import annotations

import os

import pytest

from doofus.model_router.live_model_adapter import propose_mutations
from doofus.model_router.provider_router import resolve_provider
from doofus.supervisor.controlled_cycle import DEFAULT_MODEL, DEFAULT_PROVIDER


def test_controlled_cycle_defaults_openrouter():
    assert DEFAULT_PROVIDER == "openrouter"
    assert DEFAULT_MODEL == "deepseekv4flash"


def test_openrouter_primary_when_fallbacks_disabled(monkeypatch):
    monkeypatch.setenv("DOOFUS_PROVIDER_FALLBACKS_DISABLED", "1")
    monkeypatch.setenv("DOOFUS_LIVE_PROVIDER", "openrouter")
    monkeypatch.setenv("DOOFUS_MODEL_PROVIDER", "openrouter")
    monkeypatch.setenv("DOOFUS_OPENROUTER_MODEL_ID", "deepseek/deepseek-v4-flash")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-test-key-for-unit-tests-only")
    monkeypatch.setenv("DOOFUS_FORCE_MODEL_DRY_RUN", "1")
    route = resolve_provider()
    assert route.get("provider_selected") in ("openrouter", "dry_run")
    assert route.get("provider_selected") != "cursor"


def test_cursor_not_used_without_explicit_request(monkeypatch):
    monkeypatch.setenv("DOOFUS_PROVIDER_FALLBACKS_DISABLED", "1")
    monkeypatch.setenv("DOOFUS_LIVE_PROVIDER", "openrouter")
    monkeypatch.setenv("DOOFUS_PREFER_CURSOR", "0")
    monkeypatch.setenv("CURSOR_API_KEY", "cursor-test-key")
    monkeypatch.setenv("DOOFUS_OPENROUTER_MODEL_ID", "deepseek/deepseek-v4-flash")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-test-key-for-unit-tests-only")
    monkeypatch.setenv("DOOFUS_FORCE_MODEL_DRY_RUN", "1")
    route = resolve_provider()
    assert route.get("provider_selected") != "cursor"


def test_dry_run_no_network(monkeypatch):
    monkeypatch.setenv("DOOFUS_FORCE_MODEL_DRY_RUN", "1")
    monkeypatch.setenv("DOOFUS_MODEL_PROVIDER", "openrouter")
    monkeypatch.setenv("DOOFUS_OPENROUTER_MODEL_ID", "deepseek/deepseek-v4-flash")
    result = propose_mutations({"generation": 0, "prompt": "test"})
    assert result.get("classification") in ("DOOFUS_MODEL_DRY_RUN", "DOOFUS_OPENROUTER_LANE_UNAVAILABLE", "DOOFUS_MODEL_GATE_BLOCKED")


def test_live_launch_env_openrouter():
    from doofus.reports.cycle_orchestrator import live_launch_env

    env = live_launch_env()
    assert env.get("DOOFUS_MODEL_PROVIDER") == "openrouter"
    assert env.get("DOOFUS_PROVIDER_FALLBACKS_DISABLED") == "1"
