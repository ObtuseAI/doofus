"""Install Desktop secret into user env and gitignored .env — REDACTED only."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from doofus.model_router.desktop_secret_loader import load_desktop_secret, safe_report

ENV_FILE = Path(r"C:\sai-auth-doofus\.env")


def main() -> int:
    meta = load_desktop_secret()
    if not meta.get("secret_found"):
        print(json.dumps({"classification": "B1043_OPENROUTER_TASK_ENV_INSTALL_BLOCKED", "reason": "secret_not_found"}))
        return 1
    val = meta.get("_value")
    if not val:
        return 1
    ENV_FILE.write_text(f"OPENROUTER_API_KEY={val}\n", encoding="utf-8", newline="\n")
    os.environ["OPENROUTER_API_KEY"] = val
    subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "[Environment]::SetEnvironmentVariable('OPENROUTER_API_KEY', $env:DOOFUS_KEY_SYNC, 'User')",
        ],
        env={**os.environ, "DOOFUS_KEY_SYNC": val},
        check=True,
    )
    print(json.dumps({
        "classification": "B1043_OPENROUTER_TASK_ENV_INSTALL_PASS",
        "desktop": safe_report(meta),
        "secret_value": "REDACTED",
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
