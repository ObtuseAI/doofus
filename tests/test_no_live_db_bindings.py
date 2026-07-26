"""Guard: no doofus module may reach the live runtime workspace during tests.

Modules that do `from doofus.core.doofus_paths import METRICS_DB` (or STATE,
CONTROL, ...) bind the path at import time, escaping the doofus_paths patches in
conftest. An unpatched binding once made a test COUNT(*)-scan the live 39 GB
metrics DB — an effectively infinite hang. conftest's redirect_live_bindings()
sweeps loaded modules; this test proves that sweep reaches closure over the
ENTIRE package: it imports every doofus module, re-runs the sweep, and fails if
any live binding survives.
"""
from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path

import pytest

import doofus
from conftest import LIVE_PATH_ATTRS, redirect_live_bindings
from doofus.core.doofus_paths import CANONICAL_RUNTIME


def test_redirect_live_bindings_reaches_closure():
    import sys

    for m in pkgutil.walk_packages(doofus.__path__, prefix="doofus."):
        try:
            importlib.import_module(m.name)
        except Exception:
            continue  # optional deps (ribs, dspy, UI extras) may be absent

    mp = pytest.MonkeyPatch()
    try:
        redirect_live_bindings(mp)
        canonical_runtime = str(CANONICAL_RUNTIME).lower()
        leftovers = []
        for name, mod in list(sys.modules.items()):
            if not name.startswith("doofus") or mod is None:
                continue
            for attr in LIVE_PATH_ATTRS:
                bound = getattr(mod, attr, None)
                if isinstance(bound, Path) and str(bound).lower().startswith(canonical_runtime):
                    leftovers.append(f"{name}.{attr}")
        assert not leftovers, (
            "live runtime bindings survived redirect_live_bindings(): "
            + ", ".join(leftovers)
        )
    finally:
        mp.undo()
