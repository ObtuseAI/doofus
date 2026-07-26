"""Tests for auth source resolver."""
import os

from doofus.model_router.auth_source_resolver import resolve_auth_source


def test_process_env_precedence(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-process")
    r = resolve_auth_source(include_desktop=False)
    assert r["source_name"] == "process_env"
    assert r["key_shape"] == "openrouter_like"
