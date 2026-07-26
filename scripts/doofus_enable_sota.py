"""Enable SOTA recursive evolution — user-scope env + run switch."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    from doofus.config.evolution_runtime_config import DEFAULTS as EVO
    from doofus.config.proof_builder_runtime_config import DEFAULTS as PB
    from doofus.config.meta_evolution_config import DEFAULTS as META, apply_defaults
    from doofus.config.proof_builder_runtime_config import bootstrap_autonomous_runtime
    from doofus.safety.on_off_switch import clear_emergency, start
    from doofus.core.doofus_paths import STATE

    merged = {**EVO, **PB, **META}
    for name, value in merged.items():
        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"[Environment]::SetEnvironmentVariable('{name}', $env:DOOFUS_VAL_SYNC, 'User')"],
            env={**os.environ, "DOOFUS_VAL_SYNC": value},
            check=True,
        )
        os.environ[name] = value

    apply_defaults(force=True)
    bootstrap_autonomous_runtime(force=True)

    clear_emergency()
    switch = start()

    STATE.mkdir(parents=True, exist_ok=True)
    marker = STATE / "sota_enabled.json"
    marker.write_text(json.dumps({
        "classification": "DOOFUS_SOTA_ENABLED",
        "meta_evolution": META,
        "run_switch": switch,
    }, indent=2), encoding="utf-8")

    print(json.dumps({
        "classification": "DOOFUS_SOTA_ENABLED",
        "run_switch": switch,
        "highlights": {
            "DOOFUS_META_EVOLUTION_MODE": META["DOOFUS_META_EVOLUTION_MODE"],
            "DOOFUS_ARENA_MODE": META["DOOFUS_ARENA_MODE"],
            "DOOFUS_CODEEVOLVE_AUTO_APPLY": META["DOOFUS_CODEEVOLVE_AUTO_APPLY"],
            "DOOFUS_GEPA_MIN_TRACES": META["DOOFUS_GEPA_MIN_TRACES"],
        },
        "marker": str(marker),
        "note": "Restart supervisor/dashboard to pick up user env vars in new processes.",
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
