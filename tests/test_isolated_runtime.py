from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from doofus.runtime.isolated_runtime import isolated_runtime_copy


def test_isolated_runtime_child_process_uses_isolated_metrics_db():
    with isolated_runtime_copy(clear_stop_flags=False) as iso:
        code = (
            "import json; "
            "from doofus.core.doofus_paths import ROOT, METRICS_DB; "
            "print(json.dumps({'root': str(ROOT), 'metrics_db': str(METRICS_DB)}))"
        )
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            check=True,
        )
        payload = json.loads(proc.stdout.strip().splitlines()[-1])

    assert payload["root"] == str(iso.root)
    assert payload["metrics_db"] == str(iso.metrics_db)
