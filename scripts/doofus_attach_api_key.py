"""Fix .env BOM and set user-level OPENROUTER_API_KEY for scheduled tasks."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(r"C:\sai-auth-doofus")
ENV_FILE = ROOT / ".env"


def read_key() -> str:
    if not ENV_FILE.exists():
        sys.exit("missing .env")
    for line in ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line.startswith("OPENROUTER_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    sys.exit("OPENROUTER_API_KEY not found in .env")


def main() -> int:
    val = read_key()
    ENV_FILE.write_text(f"OPENROUTER_API_KEY={val}\n", encoding="utf-8", newline="\n")

    os.environ["OPENROUTER_API_KEY"] = val
    subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "[System.Environment]::SetEnvironmentVariable('OPENROUTER_API_KEY', $env:DOOFUS_KEY_SYNC, 'User')",
        ],
        env={**os.environ, "DOOFUS_KEY_SYNC": val},
        check=True,
    )

    from doofus.safety.secret_guard import key_present
    from doofus.core.doofus_config import DoofusConfig

    print(
        "ok",
        "key_present",
        key_present(),
        "model_mode",
        DoofusConfig.from_env().model_mode,
        "user_env_set",
        True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
