"""Load local .env — never committed."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(r"C:\sai-auth-doofus")
ENV_FILE = ROOT / ".env"


def load_doofus_env() -> bool:
    if os.environ.get("DOOFUS_DISABLE_SECRET_DISCOVERY", "").strip() == "1":
        return False
    if not ENV_FILE.exists():
        return False
    try:
        from dotenv import load_dotenv

        load_dotenv(ENV_FILE, override=False, encoding="utf-8-sig")
        return bool(os.environ.get("OPENROUTER_API_KEY", "").strip())
    except ImportError:
        text = ENV_FILE.read_text(encoding="utf-8-sig")
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            os.environ[key.strip().lstrip("\ufeff")] = val.strip().strip('"').strip("'")
        return bool(os.environ.get("OPENROUTER_API_KEY", "").strip())
