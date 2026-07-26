# -*- coding: utf-8 -*-
"""Capture and export SOTA KPI snapshot."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    from doofus.reports.sota_kpi_tracker import capture_kpi_snapshot, export_kpi_to_shared

    snap = capture_kpi_snapshot()
    export = export_kpi_to_shared(snap)
    print(json.dumps({**snap, "export": export}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
