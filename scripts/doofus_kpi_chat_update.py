# -*- coding: utf-8 -*-
"""Refresh KPI snapshot for chat updates (no shared-folder hourly export)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    from doofus.reports.sota_kpi_tracker import publish_hourly_kpi_report

    result = publish_hourly_kpi_report(chat_only=True)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
