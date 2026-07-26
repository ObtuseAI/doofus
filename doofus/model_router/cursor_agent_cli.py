# -*- coding: utf-8 -*-
"""Local Cursor Agent CLI transport for Doofus mutation proposals."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from doofus.config.cursor_composer_config import cursor_model_id
from doofus.core.doofus_paths import ROOT
from doofus.model_router.model_secret_redactor import redact_secrets

DEFAULT_AGENT_PATHS = (
    Path(os.environ.get("LOCALAPPDATA", "")) / "cursor-agent" / "agent.cmd",
    Path(os.environ.get("LOCALAPPDATA", "")) / "cursor-agent" / "agent.ps1",
)
AGENT_WORKSPACE_DIR = ROOT / "runtime" / "cursor-agent-cli-workspace"

SAFE_TRAITS = (
    "replay_stability",
    "proof_density",
    "generalization_pressure",
    "arena_agent_arcade",
    "compounding_bias",
)


def _requested_proposal_count(context: dict[str, Any]) -> int:
    requested = int(context.get("requested_proposals") or 0)
    if requested > 0:
        return max(1, min(requested, 2))
    pressure = float(context.get("pressure_level") or 1.0)
    return 2 if pressure >= 2 else 1


def resolve_agent_executable() -> str | None:
    custom = os.environ.get("DOOFUS_CURSOR_AGENT_BIN", "").strip()
    if custom and Path(custom).exists():
        return custom
    found = shutil.which("agent")
    if found:
        return found
    for path in DEFAULT_AGENT_PATHS:
        if path.exists():
            return str(path)
    return None


def agent_cli_available() -> bool:
    if os.environ.get("DOOFUS_CURSOR_USE_AGENT_CLI", "1") != "1":
        return False
    return resolve_agent_executable() is not None


def agent_workspace() -> Path:
    custom = os.environ.get("DOOFUS_CURSOR_AGENT_WORKSPACE", "").strip()
    path = Path(custom) if custom else AGENT_WORKSPACE_DIR
    path.mkdir(parents=True, exist_ok=True)
    note = path / "README.txt"
    if not note.exists():
        note.write_text(
            "Dedicated workspace for Doofus Cursor agent CLI mutation prompts.\n"
            "This folder is intentionally minimal so the agent focuses on the prompt payload.\n",
            encoding="utf-8",
        )
    return path


def build_mutation_prompt(context: dict[str, Any]) -> str:
    ctx = json.dumps(context, default=str)
    max_ctx = int(os.environ.get("DOOFUS_CURSOR_PROMPT_MAX_CHARS", "4500"))
    if len(ctx) > max_ctx:
        ctx = ctx[:max_ctx]
    proposal_count = _requested_proposal_count(context)
    example_traits = list(SAFE_TRAITS[: max(2, proposal_count)])
    contract = {
        "proposals": [
            {
                "traits": example_traits,
                "rationale": "short"
            }
            for _ in range(proposal_count)
        ]
    }
    instructions = [
        "Return one minified JSON object only.",
        "No prose. No markdown. No code fences.",
        "No tool use. No file inspection.",
        f"Top-level shape must be: {json.dumps(contract, separators=(',', ':'))}",
        f"Use only these safe traits: {', '.join(SAFE_TRAITS)}.",
        "Never propose network egress, credentials, or forbidden execution traits.",
        f"Return exactly {proposal_count} proposal object(s).",
        "If you are uncertain, still return valid JSON with an empty proposals array.",
    ]
    return "\n".join(instructions) + f"\n\nContext:\n{ctx}"


def probe_agent_auth() -> dict[str, Any]:
    agent = resolve_agent_executable()
    if not agent:
        return {"available": False, "logged_in": False, "reason": "agent_cli_missing"}
    try:
        proc = subprocess.run(
            [agent, "status"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(ROOT),
        )
    except Exception as exc:
        return {"available": True, "logged_in": False, "reason": type(exc).__name__, "error": str(exc)}
    combined = f"{proc.stdout}\n{proc.stderr}".lower()
    logged_in = "not logged in" not in combined and proc.returncode == 0
    if "authentication required" in combined:
        logged_in = False
    return {
        "available": True,
        "logged_in": logged_in,
        "agent_bin": agent,
        "status_text": (proc.stdout or proc.stderr or "").strip()[:200],
    }


def _extract_response_text(stdout: str, stderr: str) -> str:
    stdout = stdout.strip()
    if not stdout:
        return stderr.strip()
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if not line:
            continue
        if line.startswith("{"):
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if payload.get("type") == "result":
                val = payload.get("result")
                if isinstance(val, str) and val.strip():
                    return val.strip()
            for key in ("result", "text", "response", "message", "content"):
                val = payload.get(key)
                if isinstance(val, str) and val.strip():
                    return val.strip()
                if isinstance(val, dict):
                    nested = val.get("text") or val.get("content")
                    if isinstance(nested, str) and nested.strip():
                        return nested.strip()
            continue
    return stdout


def propose_via_agent_cli(context: dict[str, Any]) -> dict[str, Any]:
    agent = resolve_agent_executable()
    if not agent:
        return {"ok": False, "error": "agent_cli_missing", "transport": "agent_cli"}

    model = cursor_model_id()
    prompt = build_mutation_prompt(context)
    timeout = int(os.environ.get("DOOFUS_CURSOR_TIMEOUT_SECONDS", "120"))
    workspace = agent_workspace()
    cmd = [
        agent,
        "-p",
        "--output-format",
        "json",
        "--mode",
        "ask",
        "--trust",
        "--workspace",
        str(workspace),
        "--model",
        model,
        prompt,
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(workspace),
            env=os.environ.copy(),
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "agent_cli_timeout", "transport": "agent_cli", "model": model}
    except Exception as exc:
        return {
            "ok": False,
            "error": redact_secrets(str(exc)),
            "transport": "agent_cli",
            "model": model,
        }

    combined_err = f"{proc.stdout}\n{proc.stderr}"
    if "authentication required" in combined_err.lower():
        return {
            "ok": False,
            "error": "agent_auth_required",
            "transport": "agent_cli",
            "model": model,
            "hint": "Run: agent login",
        }

    text = _extract_response_text(proc.stdout, proc.stderr)
    if not text:
        err = redact_secrets(proc.stderr or proc.stdout or "agent_cli_empty_response")
        return {"ok": False, "error": err, "transport": "agent_cli", "model": model, "returncode": proc.returncode}

    return {"ok": True, "text": text, "transport": "agent_cli", "model": model, "returncode": proc.returncode}
