"""DeepSeek V4 Flash via OpenRouter — no hardcoded credentials."""
from __future__ import annotations
import json
from dataclasses import dataclass
from typing import Any

import requests

from doofus.core.doofus_config import DoofusConfig
from doofus.model_router.model_call_ledger import record_call
from doofus.model_router.model_secret_redactor import redact_secrets
from doofus.model_router.openrouter_auth_config import ensure_auth_loaded, get_api_key_for_request, openrouter_headers
from doofus.safety.budget_guard import check_budget
from doofus.supervisor.live_model_cycle_gate import may_call_model

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

@dataclass
class DeepSeekV4FlashAdapter:
    config: DoofusConfig

    @classmethod
    def from_env(cls) -> "DeepSeekV4FlashAdapter":
        return cls(DoofusConfig.from_env())

    def status(self) -> dict[str, Any]:
        return {
            "model": self.config.model_name,
            "provider": self.config.model_provider,
            "mode": self.config.model_mode,
            "temperature": self.config.model_temperature,
            "credentials_present": bool(self.config.openrouter_api_key),
        }

    def propose_mutations(self, context: dict[str, Any]) -> dict[str, Any]:
        ensure_auth_loaded()
        gate = may_call_model(live_requested=True)
        budget = check_budget(self.config)
        if not budget["ok"]:
            return {"classification": "DOOFUS_MODEL_BUDGET_BLOCKED", "proposals": [], "budget": budget}
        if not gate["allowed"] and self.config.model_mode == "live":
            return {"classification": "DOOFUS_MODEL_GATE_BLOCKED", "reason": gate.get("reason"), "mode": "blocked"}

        prompt_text = context.get("prompt")
        if prompt_text:
            prompt = prompt_text
        elif context.get("system_prompt"):
            import json as _json
            prompt = context["system_prompt"] + "\n\nContext:\n" + _json.dumps(
                {k: v for k, v in context.items() if k not in ("system_prompt", "prompt")},
                default=str,
            )[:3000]
        else:
            prompt = json.dumps({"task": "propose_local_mutation_traits", "context": context}, default=str)[:4000]

        max_tokens = int(context.get("max_tokens", 512))
        temperature = float(context.get("temperature", self.config.model_temperature))

        if self.config.model_mode == "dry_run":
            out = json.dumps({"proposals": [{"traits": ["replay_stability", "proof_density"], "rationale": "dry_run_stub"}]})
            record_call(self.config.model_name, "dry_run", out, tokens_est=0, cost_est=0.0)
            return {"classification": "DOOFUS_MODEL_DRY_RUN", "proposals": [{"traits": ["replay_stability", "proof_density"]}], "mode": "dry_run", "raw": out}

        api_key, auth_source = get_api_key_for_request()
        if not api_key:
            return {"classification": "DOOFUS_MODEL_NO_KEY", "mode": "dry_run", "auth_source": auth_source}

        headers = openrouter_headers(api_key)
        body = {
            "model": self.config.model_name,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
        }
        try:
            r = requests.post(OPENROUTER_URL, headers=headers, json=body, timeout=60)
            r.raise_for_status()
            data = r.json()
            content = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
            tokens_est = usage.get("total_tokens", max_tokens)
            cost_est = round(tokens_est * 0.000002, 6)
            record_call(self.config.model_name, self.config.model_provider, content, tokens_est=tokens_est, cost_est=cost_est)
            return {
                "classification": "DOOFUS_MODEL_LIVE",
                "raw": content,
                "mode": "live",
                "tokens_est": tokens_est,
                "cost_est": cost_est,
                "auth_source_name": auth_source.get("source_name", "unknown"),
            }
        except Exception as exc:
            safe_err = redact_secrets(str(exc))
            status_code = None
            if hasattr(exc, "response") and exc.response is not None:
                status_code = getattr(exc.response, "status_code", None)
            return {
                "classification": "DOOFUS_MODEL_ERROR",
                "error": safe_err,
                "mode": "live",
                "provider_status_code": status_code,
                "auth_source_name": auth_source.get("source_name", "unknown"),
            }
