# -*- coding: utf-8 -*-
"""Cursor Composer 2.5 adapter - local agent CLI or SDK bridge."""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from typing import Any

from doofus.config.cursor_composer_config import cursor_model_id
from doofus.core.doofus_config import DoofusConfig
from doofus.core.doofus_paths import ROOT
from doofus.model_router.cursor_agent_cli import (
    agent_cli_available,
    probe_agent_auth,
    propose_via_agent_cli,
)
from doofus.model_router.model_call_ledger import record_call
from doofus.model_router.model_secret_redactor import redact_secrets
from doofus.safety.budget_guard import check_budget
from doofus.supervisor.live_model_cycle_gate import may_call_model

BRIDGE_DIR = ROOT / "scripts" / "cursor-bridge"
BRIDGE_SCRIPT = BRIDGE_DIR / "mutation_bridge.mjs"


@dataclass
class CursorComposerAdapter:
    config: DoofusConfig

    @classmethod
    def from_env(cls) -> "CursorComposerAdapter":
        return cls(DoofusConfig.from_env())

    def status(self) -> dict[str, Any]:
        api_key = bool(os.environ.get("CURSOR_API_KEY", "").strip())
        auth_token = bool(os.environ.get("CURSOR_AUTH_TOKEN", "").strip())
        cli = probe_agent_auth()
        live = api_key or auth_token or cli.get("logged_in")
        transport = "sdk" if api_key else ("agent_cli" if cli.get("logged_in") else "dry_run")
        return {
            "model": cursor_model_id(),
            "provider": "cursor",
            "mode": "live" if live else "dry_run",
            "transport": transport,
            "bridge": str(BRIDGE_SCRIPT),
            "agent_cli": cli,
            "credentials_present": live,
            "cursor_api_key_present": api_key,
        }

    def propose_mutations(self, context: dict[str, Any]) -> dict[str, Any]:
        if os.environ.get("DOOFUS_FORCE_MODEL_DRY_RUN", "0") == "1":
            return self._dry_run(context)
        api_key = os.environ.get("CURSOR_API_KEY", "").strip()
        prefer_cli = os.environ.get("DOOFUS_CURSOR_PREFER_AGENT_CLI", "1") == "1"

        if api_key and not prefer_cli:
            return self._propose_live(context, via="sdk")

        if agent_cli_available():
            gate = may_call_model(live_requested=True)
            budget = check_budget(self.config)
            if budget["ok"] and gate["allowed"]:
                cli_result = propose_via_agent_cli(context)
                if cli_result.get("ok"):
                    return self._format_live_result(cli_result, via="agent_cli")
                if cli_result.get("error") == "agent_auth_required" and api_key:
                    return self._propose_live(context, via="sdk")

        if api_key:
            return self._propose_live(context, via="sdk")

        if agent_cli_available():
            auth = probe_agent_auth()
            if not auth.get("logged_in"):
                dry = self._dry_run(context)
                dry["cursor_auth_hint"] = "Run once: agent login"
                return dry

        return self._dry_run(context)

    def _propose_live(self, context: dict[str, Any], *, via: str) -> dict[str, Any]:
        gate = may_call_model(live_requested=True)
        budget = check_budget(self.config)
        if not budget["ok"]:
            return {"classification": "DOOFUS_MODEL_BUDGET_BLOCKED", "proposals": [], "budget": budget}
        if not gate["allowed"]:
            return {"classification": "DOOFUS_MODEL_GATE_BLOCKED", "reason": gate.get("reason"), "mode": "blocked"}

        if via == "agent_cli":
            cli_result = propose_via_agent_cli(context)
            if cli_result.get("ok"):
                return self._format_live_result(cli_result, via="agent_cli")
            return {
                "classification": "DOOFUS_CURSOR_ERROR",
                "error": redact_secrets(str(cli_result.get("error", "agent_cli_failed"))),
                "mode": "live",
                "provider": "cursor",
                "transport": "agent_cli",
                "hint": cli_result.get("hint"),
            }

        if not BRIDGE_SCRIPT.exists():
            return {
                "classification": "DOOFUS_CURSOR_BRIDGE_MISSING",
                "mode": "blocked",
                "error": "mutation_bridge.mjs not found",
            }

        timeout = int(os.environ.get("DOOFUS_CURSOR_TIMEOUT_SECONDS", "120"))
        env = os.environ.copy()
        env["DOOFUS_ROOT"] = str(ROOT)
        env["DOOFUS_CURSOR_MODEL"] = cursor_model_id()

        try:
            proc = subprocess.run(
                ["node", str(BRIDGE_SCRIPT)],
                input=json.dumps(context, default=str),
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(BRIDGE_DIR),
                env=env,
            )
        except subprocess.TimeoutExpired:
            return {"classification": "DOOFUS_CURSOR_TIMEOUT", "mode": "live", "provider": "cursor", "transport": "sdk"}
        except Exception as exc:
            return {
                "classification": "DOOFUS_CURSOR_ERROR",
                "error": redact_secrets(str(exc)),
                "mode": "live",
                "provider": "cursor",
                "transport": "sdk",
            }

        if proc.returncode != 0 and not proc.stdout.strip():
            err = redact_secrets(proc.stderr or proc.stdout or "bridge_failed")
            return {"classification": "DOOFUS_CURSOR_ERROR", "error": err, "mode": "live", "provider": "cursor", "transport": "sdk"}

        try:
            bridge = json.loads(proc.stdout.strip().splitlines()[-1])
        except (json.JSONDecodeError, IndexError):
            return {
                "classification": "DOOFUS_CURSOR_PARSE_ERROR",
                "raw": redact_secrets(proc.stdout[:500]),
                "mode": "live",
                "provider": "cursor",
                "transport": "sdk",
            }

        if not bridge.get("ok"):
            return {
                "classification": "DOOFUS_CURSOR_ERROR",
                "error": redact_secrets(str(bridge.get("error", "unknown"))),
                "mode": "live",
                "provider": "cursor",
                "transport": "sdk",
            }

        return self._format_live_result(
            {
                "ok": True,
                "text": str(bridge.get("text") or ""),
                "model": bridge.get("model", cursor_model_id()),
                "status": bridge.get("status"),
            },
            via="sdk",
        )

    def _format_live_result(self, result: dict[str, Any], *, via: str) -> dict[str, Any]:
        text = str(result.get("text") or "")
        tokens_est = max(len(text) // 4, 256)
        cost_est = round(tokens_est * 0.000004, 6)
        record_call(cursor_model_id(), f"cursor_{via}", text, tokens_est=tokens_est, cost_est=cost_est)
        out: dict[str, Any] = {
            "classification": "DOOFUS_MODEL_LIVE",
            "raw": text,
            "mode": "live",
            "provider": "cursor",
            "transport": via,
            "cursor_model": result.get("model", cursor_model_id()),
            "tokens_est": tokens_est,
            "cost_est": cost_est,
        }
        if via == "sdk":
            out["cursor_status"] = result.get("status")
        return out

    def _dry_run(self, context: dict[str, Any]) -> dict[str, Any]:
        proposals = [
            {"traits": ["replay_stability", "proof_density", "compounding_focus"], "rationale": "cursor_dry_run"},
            {"traits": ["arena_agent_arcade", "generalization_pressure"], "rationale": "cursor_dry_run_2"},
        ]
        out = json.dumps({"proposals": proposals})
        record_call(cursor_model_id(), "dry_run", out, tokens_est=0, cost_est=0.0)
        return {
            "classification": "DOOFUS_MODEL_DRY_RUN",
            "proposals": proposals,
            "mode": "dry_run",
            "provider": "cursor",
            "transport": "dry_run",
            "raw": out,
        }
