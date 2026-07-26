"""Tests for Cursor Composer adapter and routing."""
from __future__ import annotations

import json

from doofus.model_router.cursor_composer_adapter import CursorComposerAdapter
from doofus.model_router.live_model_adapter import propose_mutations
from doofus.model_router.provider_router import resolve_provider


def _patch_gates(monkeypatch):
    monkeypatch.setattr(
        "doofus.model_router.cursor_composer_adapter.may_call_model",
        lambda **_: {"allowed": True},
    )
    monkeypatch.setattr(
        "doofus.model_router.cursor_composer_adapter.check_budget",
        lambda _: {"ok": True},
    )


def test_cursor_routes_when_key_present(monkeypatch):
    monkeypatch.setattr("doofus.model_router.provider_router.load_doofus_env", lambda: False)
    monkeypatch.setenv("DOOFUS_MODEL_PROVIDER", "cursor")
    monkeypatch.setenv("CURSOR_API_KEY", "cursor-" + ("t" * 24))
    monkeypatch.setenv("DOOFUS_CURSOR_MODEL", "composer-2.5")
    for k in ("OPENROUTER_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    r = resolve_provider()
    assert r["provider_selected"] == "cursor"
    assert r["model_name"] == "composer-2.5"
    assert r["live_provider_ready"] is True


def test_cursor_dry_run_without_key(monkeypatch):
    monkeypatch.setenv("DOOFUS_MODEL_PROVIDER", "cursor")
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    monkeypatch.setattr(
        "doofus.model_router.cursor_composer_adapter.agent_cli_available",
        lambda: False,
    )
    adapter = CursorComposerAdapter.from_env()
    result = adapter.propose_mutations({"generation": 1, "baseline": 0.9})
    assert result["classification"] == "DOOFUS_MODEL_DRY_RUN"
    assert result["provider"] == "cursor"
    assert len(result.get("proposals") or []) >= 1


def test_cursor_agent_cli_live(monkeypatch):
    _patch_gates(monkeypatch)
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    monkeypatch.setenv("DOOFUS_CURSOR_PREFER_AGENT_CLI", "1")
    monkeypatch.setattr(
        "doofus.model_router.cursor_composer_adapter.agent_cli_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "doofus.model_router.cursor_composer_adapter.probe_agent_auth",
        lambda: {"available": True, "logged_in": True},
    )
    monkeypatch.setattr(
        "doofus.model_router.cursor_composer_adapter.propose_via_agent_cli",
        lambda ctx: {
            "ok": True,
            "text": json.dumps({"proposals": [{"traits": ["replay_stability"], "rationale": "cli"}]}),
            "model": "composer-2.5",
            "transport": "agent_cli",
        },
    )
    monkeypatch.setattr(
        "doofus.model_router.cursor_composer_adapter.record_call",
        lambda *a, **k: None,
    )
    result = CursorComposerAdapter.from_env().propose_mutations({"generation": 3})
    assert result["classification"] == "DOOFUS_MODEL_LIVE"
    assert result["transport"] == "agent_cli"


def test_cursor_dry_run_hints_login(monkeypatch):
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    monkeypatch.setattr(
        "doofus.model_router.cursor_composer_adapter.agent_cli_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "doofus.model_router.cursor_composer_adapter.probe_agent_auth",
        lambda: {"available": True, "logged_in": False},
    )
    result = CursorComposerAdapter.from_env().propose_mutations({"generation": 1})
    assert result["classification"] == "DOOFUS_MODEL_DRY_RUN"
    assert result.get("cursor_auth_hint") == "Run once: agent login"


def test_live_adapter_cursor_dry_run(monkeypatch):
    monkeypatch.setattr("doofus.model_router.live_model_adapter.load_doofus_env", lambda: False)
    monkeypatch.setattr("doofus.model_router.provider_router.load_doofus_env", lambda: False)
    monkeypatch.setenv("DOOFUS_MODEL_PROVIDER", "cursor")
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    _patch_gates(monkeypatch)
    monkeypatch.setattr(
        "doofus.model_router.cursor_composer_adapter.agent_cli_available",
        lambda: False,
    )
    result = propose_mutations({"generation": 42})
    assert result["classification"] == "DOOFUS_MODEL_DRY_RUN"
    assert result.get("provider") == "cursor"


def test_cursor_adapter_parses_bridge_output(monkeypatch, tmp_path):
    bridge_dir = tmp_path / "bridge"
    bridge_dir.mkdir()
    script = bridge_dir / "mutation_bridge.mjs"
    script.write_text("// stub", encoding="utf-8")

    payload = {
        "ok": True,
        "text": json.dumps({"proposals": [{"traits": ["replay_stability"], "rationale": "test"}]}),
        "status": "completed",
        "model": "composer-2.5",
    }

    class FakeProc:
        returncode = 0
        stdout = json.dumps(payload) + "\n"
        stderr = ""

    monkeypatch.setenv("CURSOR_API_KEY", "cursor-test-key")
    monkeypatch.setattr(
        "doofus.model_router.cursor_composer_adapter.BRIDGE_SCRIPT",
        script,
    )
    monkeypatch.setattr(
        "doofus.model_router.cursor_composer_adapter.BRIDGE_DIR",
        bridge_dir,
    )
    monkeypatch.setattr(
        "doofus.model_router.cursor_composer_adapter.may_call_model",
        lambda **_: {"allowed": True},
    )
    monkeypatch.setattr(
        "doofus.model_router.cursor_composer_adapter.check_budget",
        lambda _: {"ok": True},
    )
    monkeypatch.setattr(
        "doofus.model_router.cursor_composer_adapter.subprocess.run",
        lambda *a, **k: FakeProc(),
    )
    monkeypatch.setattr(
        "doofus.model_router.cursor_composer_adapter.record_call",
        lambda *a, **k: None,
    )

    result = CursorComposerAdapter.from_env().propose_mutations({"generation": 7})
    assert result["classification"] == "DOOFUS_MODEL_LIVE"
    assert "replay_stability" in result["raw"]
