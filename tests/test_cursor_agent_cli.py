"""Tests for local Cursor agent CLI helper."""
from __future__ import annotations

import json

from doofus.model_router.cursor_agent_cli import build_mutation_prompt, propose_via_agent_cli


def test_build_mutation_prompt_uses_strict_json_contract():
    prompt = build_mutation_prompt(
        {
            "generation": 1634,
            "baseline": 0.9378,
            "pressure_level": 1.0,
            "requested_proposals": 1,
        }
    )
    assert "Return one minified JSON object only." in prompt
    assert "No tool use. No file inspection." in prompt
    assert "compounding_bias" in prompt
    assert "Return exactly 1 proposal object(s)." in prompt


def test_propose_via_agent_cli_parses_json_result(monkeypatch):
    class FakeProc:
        returncode = 0
        stdout = json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "result": '{"proposals":[{"traits":["replay_stability"],"rationale":"ok"}]}',
            }
        )
        stderr = ""

    monkeypatch.setattr("doofus.model_router.cursor_agent_cli.resolve_agent_executable", lambda: "agent")
    monkeypatch.setattr("doofus.model_router.cursor_agent_cli.subprocess.run", lambda *a, **k: FakeProc())
    result = propose_via_agent_cli({"generation": 1, "requested_proposals": 1})
    assert result["ok"] is True
    assert '"proposals"' in result["text"]
