"""Tests for OpenRouter live config."""
from __future__ import annotations

import os

import pytest

from doofus.model_router.openrouter_live_config import (
    DEEPSEEK_V4_FLASH_ALIAS,
    apply_openrouter_live_env,
    fallbacks_disabled,
    resolve_concrete_model_id,
    validate_openrouter_live_config,
)


def test_deepseek_alias_default():
    assert DEEPSEEK_V4_FLASH_ALIAS == "deepseekv4flash"


def test_missing_model_id_fails_when_required(monkeypatch):
    monkeypatch.delenv("DOOFUS_OPENROUTER_MODEL_ID", raising=False)
    monkeypatch.delenv("DOOFUS_MODEL_NAME", raising=False)
    model_id, err = resolve_concrete_model_id(require_explicit=True)
    assert model_id is None
    assert err is not None


def test_model_id_from_env(monkeypatch):
    monkeypatch.setenv("DOOFUS_OPENROUTER_MODEL_ID", "deepseek/deepseek-v4-flash")
    model_id, err = resolve_concrete_model_id(require_explicit=True)
    assert model_id == "deepseek/deepseek-v4-flash"
    assert err is None


def test_fallbacks_disabled_by_default(monkeypatch):
    monkeypatch.delenv("DOOFUS_PROVIDER_FALLBACKS_DISABLED", raising=False)
    assert fallbacks_disabled() is True


def test_apply_openrouter_live_env_disables_cursor(monkeypatch):
    env = apply_openrouter_live_env({"DOOFUS_PREFER_CURSOR": "1"})
    assert env["DOOFUS_MODEL_PROVIDER"] == "openrouter"
    assert env["DOOFUS_PREFER_CURSOR"] == "0"
    assert env["DOOFUS_CURSOR_HYBRID_FALLBACK"] == "0"


def test_validate_dry_run_without_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("DOOFUS_OPENROUTER_MODEL_ID", "deepseek/deepseek-v4-flash")
    cfg = validate_openrouter_live_config(dry_run=True)
    assert cfg["provider"] == "openrouter"
    assert cfg["model_alias"] == "deepseekv4flash"


def test_missing_api_key_blocks_live(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    monkeypatch.setenv("DOOFUS_OPENROUTER_API_KEY", "")
    monkeypatch.setenv("DOOFUS_OPENROUTER_MODEL_ID", "deepseek/deepseek-v4-flash")
    with __import__("unittest.mock").mock.patch("doofus.model_router.openrouter_live_config.resolve_api_key_present", return_value=False):
        cfg = validate_openrouter_live_config(dry_run=False, require_model_id=True)
    assert cfg["ready"] is False
    assert any("OPENROUTER_API_KEY" in b for b in cfg["blockers"])
