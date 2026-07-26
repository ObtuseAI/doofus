"""Run B1117 validation then post-run phases."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = ROOT / ".venv_doofus" / "Scripts" / "python.exe"
ORCH = ROOT / "scripts" / "doofus_fully_autonomous_orchestrator.py"


def main() -> None:
    for phase in ("b1117", "b1118", "b1119", "b1120"):
        rc = subprocess.call([str(PY), str(ORCH), "--phase", phase], cwd=str(ROOT))
        if rc != 0 and phase != "b1117":
            sys.exit(rc)


if __name__ == "__main__":
    main()
