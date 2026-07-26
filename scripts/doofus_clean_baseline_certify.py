# -*- coding: utf-8 -*-
"""Write clean baseline certification reports."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main(argv: list[str] | None = None) -> int:
    argv = argv or sys.argv[1:]
    action = argv[0] if argv else "precheck"
    from doofus.reports.clean_baseline import (
        certify_runtime_baseline,
        search_restore_sources,
        write_precheck_report,
    )

    if action == "precheck":
        print(json.dumps(write_precheck_report(), indent=2, default=str))
        return 0
    if action == "search":
        print(json.dumps(search_restore_sources(), indent=2, default=str))
        return 0
    if action == "certify":
        search = search_restore_sources()
        print(json.dumps(certify_runtime_baseline(search), indent=2, default=str))
        return 0
    raise SystemExit(f"unknown action: {action}")


if __name__ == "__main__":
    raise SystemExit(main())
