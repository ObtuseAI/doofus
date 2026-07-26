"""Tests for OpenRouter secret file parsing."""
from doofus.model_router.openrouter_secret_source import parse_secret_text


def test_parse_env_line():
    assert parse_secret_text("OPENROUTER_API_KEY=sk-or-v1-abc") == "sk-or-v1-abc"


def test_parse_raw_key():
    assert parse_secret_text("sk-or-v1-rawkey") == "sk-or-v1-rawkey"


def test_parse_json():
    assert parse_secret_text('{"openrouter_api_key":"sk-or-v1-json"}') == "sk-or-v1-json"
