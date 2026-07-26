"""Tests for provider router."""
from doofus.model_router.provider_router import resolve_provider


def _openai_secret():
    return {
        "secret_found": True,
        "secret_source": "process_env",
        "secret_source_path": "process:OPENAI_API_KEY",
        "key_shape": "openai_like",
        "secret_length_bucket": "normal",
        "secret_value": "REDACTED",
        "_value": "sk-proj-" + ("o" * 48),
        "_env_name": "OPENAI_API_KEY",
    }


def test_openai_shape_routes_openai(monkeypatch):
    monkeypatch.setattr("doofus.model_router.provider_router.load_doofus_env", lambda: False)
    monkeypatch.setattr("doofus.model_router.provider_router.resolve_unified_secret", _openai_secret)
    monkeypatch.setattr("doofus.model_router.cursor_agent_cli.agent_cli_available", lambda: False)
    for k in (
        "OPENROUTER_API_KEY", "DOOFUS_OPENROUTER_API_KEY", "DOOFUS_MODEL_PROVIDER",
        "OPENAI_API_KEY", "DOOFUS_OPENAI_API_KEY", "CURSOR_API_KEY", "DOOFUS_PREFER_CURSOR",
        "DOOFUS_LIVE_PROVIDER",
    ):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("DOOFUS_PROVIDER_FALLBACKS_DISABLED", "1")
    monkeypatch.setenv("DOOFUS_PREFER_CURSOR", "0")
    r = resolve_provider()
    assert r["provider_selected"] == "openai"
    assert r["live_provider_ready"] is True
    assert r["deepseek_openrouter_ready"] is False


def test_openrouter_shape_routes_openrouter(monkeypatch):
    monkeypatch.setattr("doofus.model_router.provider_router.load_doofus_env", lambda: False)
    monkeypatch.setattr("doofus.model_router.provider_router.resolve_unified_secret", lambda: {
            "secret_found": True,
            "secret_source": "process_env",
            "secret_source_path": "process:OPENROUTER_API_KEY",
            "key_shape": "openrouter_like",
            "secret_length_bucket": "normal",
            "secret_value": "REDACTED",
            "_value": "sk-or-v1-" + ("r" * 48),
            "_env_name": "OPENROUTER_API_KEY",
        },
    )
    for k in ("OPENAI_API_KEY", "DOOFUS_OPENAI_API_KEY", "OPENROUTER_API_KEY", "DOOFUS_OPENROUTER_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-" + ("r" * 48))
    monkeypatch.setenv("DOOFUS_MODEL_PROVIDER", "openrouter")
    monkeypatch.setenv("DOOFUS_OPENROUTER_MODEL_ID", "deepseek/deepseek-v4-flash")
    r = resolve_provider()
    assert r["provider_selected"] == "openrouter"
    assert r["deepseek_openrouter_ready"] is True
