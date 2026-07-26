# -*- coding: utf-8 -*-
"""CLI wrapper for meta bootstrap."""
from __future__ import annotations

import json
import sys

from doofus.meta.meta_bootstrap import bootstrap_meta


def main() -> int:
    force_gepa = "--force-gepa" in sys.argv
    run_ce = "--codeevolve" in sys.argv
    result = bootstrap_meta(force_gepa=force_gepa, run_codeevolve_gen=run_ce)
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
