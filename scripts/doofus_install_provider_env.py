"""Install provider-aware env from Desktop secret — REDACTED output."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from doofus.model_router.desktop_secret_loader import safe_report, load_desktop_secret
from doofus.model_router.provider_identity import provider_for_key_shape
from doofus.model_router.provider_router import resolve_provider

ENV_FILE = Path(r"C:\sai-auth-doofus\.env")


def main() -> int:
    meta = load_desktop_secret()
    if not meta.get("secret_found"):
        print(json.dumps({"classification": "B1055_PROVIDER_TASK_ENVIRONMENT_BLOCKED", "reason": "no_desktop_secret"}))
        return 1
    val = meta.get("_value")
    shape = meta.get("key_shape", "unknown")
    provider = provider_for_key_shape(shape)
    if provider == "blocked":
        print(json.dumps({"classification": "B1055_PROVIDER_TASK_ENVIRONMENT_BLOCKED", "reason": "unknown_key_shape"}))
        return 1

    lines = []
    if provider == "openai":
        lines.append(f"OPENAI_API_KEY={val}")
        lines.append("DOOFUS_MODEL_PROVIDER=openai")
        model = os.environ.get("DOOFUS_OPENAI_MODEL", "gpt-4o-mini")
        lines.append(f"DOOFUS_OPENAI_MODEL={model}")
        os.environ["OPENAI_API_KEY"] = val
        os.environ["DOOFUS_MODEL_PROVIDER"] = "openai"
        user_vars = {"OPENAI_API_KEY": val, "DOOFUS_MODEL_PROVIDER": "openai", "DOOFUS_OPENAI_MODEL": model}
    else:
        lines.append(f"OPENROUTER_API_KEY={val}")
        lines.append("DOOFUS_MODEL_PROVIDER=openrouter")
        os.environ["OPENROUTER_API_KEY"] = val
        os.environ["DOOFUS_MODEL_PROVIDER"] = "openrouter"
        user_vars = {"OPENROUTER_API_KEY": val, "DOOFUS_MODEL_PROVIDER": "openrouter"}

    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    for name, v in user_vars.items():
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", f"[Environment]::SetEnvironmentVariable('{name}', $env:DOOFUS_KEY_SYNC, 'User')"],
            env={**os.environ, "DOOFUS_KEY_SYNC": v},
            check=True,
        )

    route = resolve_provider()
    print(json.dumps({
        "classification": "B1055_PROVIDER_TASK_ENVIRONMENT_PASS",
        "provider_selected": route.get("provider_selected"),
        "key_shape": shape,
        "desktop": safe_report(meta),
        "secret_value": "REDACTED",
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
