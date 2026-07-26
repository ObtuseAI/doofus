"""OpenAI live model adapter — no hardcoded credentials."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

import requests

from doofus.core.doofus_config import DoofusConfig
from doofus.model_router.model_call_ledger import record_call
from doofus.model_router.model_lane_config import model_for_provider
from doofus.model_router.model_secret_redactor import redact_secrets
from doofus.model_router.provider_router import resolve_provider
from doofus.safety.budget_guard import check_budget
from doofus.supervisor.live_model_cycle_gate import may_call_model

OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"

LIVE_PROMPT = (
    "Return one JSON object only. Propose one safe local-only Doofus mutation candidate with fields "
    "candidate_name, mutation_trait, expected_metric, safety_note, validation_plan. "
    "Do not include shell commands. Do not include file paths. Do not request secrets."
)


@dataclass
class OpenAIAdapter:
    config: DoofusConfig
    model_name: str

    @classmethod
    def from_env(cls) -> "OpenAIAdapter":
        route = resolve_provider()
        if route.get("provider_selected") != "openai":
            model, _ = model_for_provider("openai")
        else:
            model = route.get("model_name") or "gpt-4o-mini"
        return cls(DoofusConfig.from_env(), model or "gpt-4o-mini")

    def _api_key(self) -> str | None:
        return (
            os.environ.get("OPENAI_API_KEY", "").strip()
            or os.environ.get("DOOFUS_OPENAI_API_KEY", "").strip()
            or None
        )

    def propose_mutations(self, context: dict[str, Any]) -> dict[str, Any]:
        gate = may_call_model(live_requested=True)
        budget = check_budget(self.config)
        if not budget["ok"]:
            return {"classification": "DOOFUS_MODEL_BUDGET_BLOCKED", "mode": "blocked", "provider": "openai"}
        if not gate["allowed"]:
            return {"classification": "DOOFUS_MODEL_GATE_BLOCKED", "mode": "blocked", "provider": "openai"}

        prompt = context.get("prompt") or LIVE_PROMPT
        max_tokens = int(context.get("max_tokens", 512))
        temperature = float(context.get("temperature", self.config.model_temperature))

        key = self._api_key()
        if not key:
            return {"classification": "DOOFUS_MODEL_NO_KEY", "mode": "dry_run", "provider": "openai"}

        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        body = {
            "model": self.model_name,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
        }
        try:
            r = requests.post(OPENAI_CHAT_URL, headers=headers, json=body, timeout=60)
            r.raise_for_status()
            data = r.json()
            content = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
            tokens_est = usage.get("total_tokens", max_tokens)
            cost_est = round(tokens_est * 0.000003, 6)
            record_call(self.model_name, "openai", content, tokens_est=tokens_est, cost_est=cost_est)
            return {
                "classification": "DOOFUS_OPENAI_MODEL_LIVE",
                "raw": content,
                "mode": "live",
                "provider": "openai",
                "model": self.model_name,
                "tokens_est": tokens_est,
                "cost_est": cost_est,
            }
        except Exception as exc:
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            return {
                "classification": "DOOFUS_MODEL_ERROR",
                "error": redact_secrets(str(exc)),
                "mode": "live",
                "provider": "openai",
                "provider_status_code": status_code,
            }


def probe_openai_auth() -> dict:
    route = resolve_provider()
    if route.get("provider_selected") != "openai":
        return {
            "classification": "B1051_OPENAI_PROVIDER_LANE_BLOCKED",
            "provider_auth": "blocked",
            "reason": "provider_not_openai",
            "key_shape": route.get("key_shape"),
        }
    adapter = OpenAIAdapter.from_env()
    result = adapter.propose_mutations({"prompt": "Reply OK only.", "max_tokens": 4, "temperature": 0})
    cls = result.get("classification")
    status_code = result.get("provider_status_code")
    if cls == "DOOFUS_OPENAI_MODEL_LIVE":
        ok, auth = True, "ok"
    elif status_code == 429:
        ok, auth = True, "rate_limited"
    else:
        ok, auth = False, "failing"
    return {
        "classification": "B1051_OPENAI_PROVIDER_LANE_PASS" if ok and auth == "ok" else (
            "B1051_OPENAI_PROVIDER_LANE_PASS_WITH_NOTES" if ok else "B1051_OPENAI_PROVIDER_LANE_AUTH_BLOCKED"
        ),
        "provider_auth": auth,
        "provider_status_code": status_code or (200 if ok else 401),
        "model_name": adapter.model_name,
        "key_shape": route.get("key_shape"),
        "secret_value": "REDACTED",
        "live_provider_ready": ok,
    }
