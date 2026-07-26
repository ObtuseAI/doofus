"""Doofus configuration from environment."""
from __future__ import annotations
import os
from dataclasses import dataclass

@dataclass
class DoofusConfig:
    model_provider: str = "openrouter"
    model_name: str = "deepseek/deepseek-v4-flash"
    model_temperature: float = 0.6
    max_daily_cost_usd: float = 5.0
    max_model_calls_per_hour: int = 60
    cycle_sleep_seconds: int = 60
    min_cycle_sleep_seconds: int = 10
    dashboard_host: str = "127.0.0.1"
    dashboard_port: int = 8765

    @classmethod
    def from_env(cls) -> "DoofusConfig":
        from doofus.core.doofus_env_loader import load_doofus_env

        load_doofus_env()
        provider = os.environ.get("DOOFUS_MODEL_PROVIDER", "auto")
        if provider == "openai":
            default_model = os.environ.get("DOOFUS_OPENAI_MODEL", "gpt-4o-mini")
        else:
            default_model = os.environ.get("DOOFUS_MODEL_NAME", "deepseek/deepseek-v4-flash")
        return cls(
            model_provider=provider if provider != "auto" else os.environ.get("DOOFUS_MODEL_PROVIDER", "openrouter"),
            model_name=os.environ.get("DOOFUS_MODEL_NAME", default_model) if provider != "openai" else default_model,
            model_temperature=float(os.environ.get("DOOFUS_MODEL_TEMPERATURE", "0.6")),
            max_daily_cost_usd=float(os.environ.get("DOOFUS_MAX_DAILY_COST_USD", "5")),
            max_model_calls_per_hour=int(os.environ.get("DOOFUS_MAX_MODEL_CALLS_PER_HOUR", "60")),
            cycle_sleep_seconds=int(os.environ.get("DOOFUS_CYCLE_SLEEP_SECONDS", "30")),
            min_cycle_sleep_seconds=int(os.environ.get("DOOFUS_MIN_CYCLE_SLEEP_SECONDS", "10")),
            dashboard_port=int(os.environ.get("DOOFUS_DASHBOARD_PORT", "8765")),
        )

    @property
    def openrouter_api_key(self) -> str | None:
        v = os.environ.get("OPENROUTER_API_KEY", "").strip()
        return v or None

    @property
    def openai_api_key(self) -> str | None:
        v = os.environ.get("OPENAI_API_KEY", "").strip() or os.environ.get("DOOFUS_OPENAI_API_KEY", "").strip()
        return v or None

    @property
    def model_mode(self) -> str:
        if os.environ.get("DOOFUS_FORCE_MODEL_DRY_RUN", "0") == "1":
            return "dry_run"
        if os.environ.get("DOOFUS_MODEL_PROVIDER", "").strip().lower() == "cursor":
            if os.environ.get("CURSOR_API_KEY", "").strip() or os.environ.get("CURSOR_AUTH_TOKEN", "").strip():
                return "live"
            try:
                from doofus.model_router.cursor_agent_cli import agent_cli_available, probe_agent_auth

                if agent_cli_available() and probe_agent_auth().get("logged_in"):
                    return "live"
            except Exception:
                pass
        if self.openai_api_key or self.openrouter_api_key:
            try:
                from doofus.model_router.provider_router import resolve_provider
                if resolve_provider().get("live_provider_ready"):
                    return "live"
            except Exception:
                return "live" if (self.openai_api_key or self.openrouter_api_key) else "dry_run"
        return "dry_run"
