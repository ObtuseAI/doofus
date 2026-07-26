"""Install openevolve vendor (operator approval required)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor" / "openevolve"
REPO = "https://github.com/codelion/openevolve.git"


def main() -> int:
    VENDOR.parent.mkdir(parents=True, exist_ok=True)
    if (VENDOR / ".git").exists():
        print(json.dumps({"classification": "OPENEVOLVE_ALREADY_INSTALLED", "path": str(VENDOR)}))
        return 0
    subprocess.run(["git", "clone", "--depth", "1", REPO, str(VENDOR)], check=True)
    print(json.dumps({
        "classification": "OPENEVOLVE_VENDOR_INSTALLED",
        "path": str(VENDOR),
        "provenance": REPO,
        "note": "Safe mode evaluates fitness only; module edits require DOOFUS_CODEEVOLVE_AUTO_APPLY=1",
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
