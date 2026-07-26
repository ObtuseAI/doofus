"""Tests for desktop secret loader."""
from pathlib import Path

from doofus.model_router.openrouter_secret_source import read_secret_file


def test_read_secret_file(tmp_path):
    p = tmp_path / "doofusapi.txt"
    p.write_text("OPENROUTER_API_KEY=sk-or-v1-testkey\n", encoding="utf-8")
    meta = read_secret_file(p)
    assert meta["secret_found"] is True
    assert meta["key_shape"] == "openrouter_like"
    assert meta.get("_value") == "sk-or-v1-testkey"
