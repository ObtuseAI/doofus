"""Install agent-arcade vendor (operator approval required)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor" / "agent-arcade"
REPO = "https://github.com/harishkotra/agent-arcade.git"


def main() -> int:
    VENDOR.parent.mkdir(parents=True, exist_ok=True)
    if (VENDOR / ".git").exists():
        print(json.dumps({"classification": "AGENT_ARCADE_ALREADY_INSTALLED", "path": str(VENDOR)}))
        return 0
    subprocess.run(["git", "clone", "--depth", "1", REPO, str(VENDOR)], check=True)
    print(json.dumps({
        "classification": "AGENT_ARCADE_VENDOR_INSTALLED",
        "path": str(VENDOR),
        "provenance": REPO,
        "note": "Operator approval required; no auto-download without this script.",
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
