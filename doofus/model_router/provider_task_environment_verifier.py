"""Verify scheduled task sees provider routing — REDACTED."""
from __future__ import annotations

import json

from doofus.model_router.provider_router import resolve_provider
from doofus.model_router.task_environment_verifier import verify_task_environment


def verify_provider_task_environment() -> dict:
    base = verify_task_environment()
    route = resolve_provider()
    return {
        **base,
        "provider_selected": route.get("provider_selected"),
        "live_provider_ready": route.get("live_provider_ready"),
        "deepseek_openrouter_ready": route.get("deepseek_openrouter_ready"),
        "key_shape": route.get("key_shape"),
    }


def main() -> int:
    print(json.dumps(verify_provider_task_environment(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
