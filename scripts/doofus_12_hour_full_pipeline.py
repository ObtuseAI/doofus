"""Chain post-run phases after 12-hour wait completes."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = ROOT / ".venv_doofus" / "Scripts" / "python.exe"
ORCH = ROOT / "scripts" / "doofus_12_hour_orchestrator.py"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--from-phase", default="b1091", choices=["b1091", "post", "b1096", "b1097"])
    args = p.parse_args()
    phases = ["b1091", "post", "b1096", "b1097"]
    start = phases.index(args.from_phase)
    for phase in phases[start:]:
        rc = subprocess.call([str(PY), str(ORCH), "--phase", phase], cwd=str(ROOT))
        if rc != 0:
            sys.exit(rc)


if __name__ == "__main__":
    main()
