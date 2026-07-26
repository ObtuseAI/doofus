"""Run B1105 60-min conversion then post-run phases."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = ROOT / ".venv_doofus" / "Scripts" / "python.exe"
ORCH = ROOT / "scripts" / "doofus_proof_builder_orchestrator.py"


def main() -> None:
    for phase in ("b1105", "b1106", "b1107", "b1108"):
        rc = subprocess.call([str(PY), str(ORCH), "--phase", phase], cwd=str(ROOT))
        if rc != 0:
            sys.exit(rc)


if __name__ == "__main__":
    main()
