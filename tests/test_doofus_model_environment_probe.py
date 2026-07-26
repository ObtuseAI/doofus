"""Tests for model environment probe."""
from unittest.mock import patch

from doofus.model_router.model_environment_probe import probe_model_environment


def test_probe_returns_redacted(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-" + ("p" * 48))
    monkeypatch.setenv("DOOFUS_MODEL_PROVIDER", "openrouter")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with patch("doofus.model_router.model_environment_probe.probe_openai_auth", return_value={"provider_auth": "ok"}):
        with patch("doofus.model_router.openrouter_auth_probe.probe_current_auth", return_value={"provider_auth": "ok", "status_code": 200}):
            doc = probe_model_environment()
    assert doc["openrouter_api_key_value"] == "REDACTED"
    assert "sk-or" not in str(doc)
