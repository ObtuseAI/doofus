"""Tests for secret source validator."""
from doofus.model_router.secret_source_validator import classify_key_shape, length_bucket, validate_secret_value


def test_length_bucket():
    assert length_bucket(0) == "unknown"
    assert length_bucket(30) == "short"
    assert length_bucket(80) == "normal"
    assert length_bucket(200) == "long"


def test_classify_key_shape():
    assert classify_key_shape("sk-or-v1-test") == "openrouter_like"
    assert classify_key_shape("sk-proj-test") == "openai_like"
    assert validate_secret_value("sk-or-v1-abc")["secret_found"] is True
