"""Install always-on evolution env vars at user scope (no secrets)."""
from __future__ import annotations

import json
import os
import subprocess

from doofus.config.evolution_runtime_config import DEFAULTS as EVO
from doofus.config.proof_builder_runtime_config import DEFAULTS as PB
from doofus.config.meta_evolution_config import DEFAULTS as META


def main() -> int:
    merged = {**EVO, **PB, **META}
    for name, value in merged.items():
        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"[Environment]::SetEnvironmentVariable('{name}', $env:DOOFUS_VAL_SYNC, 'User')"],
            env={**os.environ, "DOOFUS_VAL_SYNC": value},
            check=True,
        )
        os.environ[name] = value
    print(json.dumps({"classification": "B1111_EVOLUTION_ENV_INSTALLED", "vars": list(merged.keys())}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
