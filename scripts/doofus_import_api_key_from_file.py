"""Import OPENROUTER_API_KEY from Desktop/file into .env and user env. Never prints the key."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from doofus.model_router.desktop_secret_loader import load_desktop_secret, safe_report

ROOT = Path(r"C:\sai-auth-doofus")
ENV_FILE = ROOT / ".env"


def main() -> int:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if src:
        from doofus.model_router.openrouter_secret_source import read_secret_file
        meta = read_secret_file(src)
    else:
        meta = load_desktop_secret()
    if not meta.get("secret_found"):
        sys.exit("secret not found")
    val = meta.get("_value")
    if not val:
        sys.exit("empty secret")
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
    from doofus.safety.secret_guard import key_present
    from doofus.core.doofus_config import DoofusConfig

    print(json.dumps({
        "sync_ok": True,
        "desktop": safe_report(meta),
        "key_present": key_present(),
        "model_mode": DoofusConfig.from_env().model_mode,
        "secret_value": "REDACTED",
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
