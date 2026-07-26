"""Isolation and sealing for the held-out benchmark suite.

The benchmark suite is *held out*: the evolution loops (CodeEvolve, GEPA,
A-Evolve, the metacognitive cortex) must never be able to read the answers
while optimizing, otherwise "self-improvement" would just be overfitting to
the yardstick.

Two independent mechanisms enforce that here:

1. Protected-root containment (the codebase's existing mechanism).
   ``SEALED_DIR`` is registered in
   ``doofus.meta.codeevolve.project_registry._STATIC_PROTECTED_ROOTS`` so that
   ``is_protected_path`` returns ``True`` for it. The project registry's
   ``validate_project`` (rejects with ``protected_root``) and
   ``resolve_target_module`` (rejects with ``protected_path``) therefore refuse
   to ever register, resolve, mutate, or read any evolution target that
   overlaps the sealed directory. This is the same guard that keeps the engine
   out of ``C:\\sai-auth`` and the Doofus runtime root.

2. Hashed answers (defence in depth). Code-repair expected outputs are stored
   only as SHA-256 digests, never plaintext, so even a candidate that somehow
   read the sealed file cannot echo the answer — it must actually compute it.

The runner is the only component that opens the sealed directory, and only at
scoring time (after a candidate has already been produced).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

# Public task inputs the engine is *allowed* to see live under tasks/.
TASKS_DIR = Path(__file__).resolve().parent / "tasks"

# Sealed answers the engine must NEVER see during optimization live here.
SEALED_DIR = Path(__file__).resolve().parent / "_sealed"


def sha256_hex(text: str) -> str:
    """Stable SHA-256 hex digest of a string."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_json(value: Any) -> str:
    """Canonical, key-sorted JSON encoding used for sealing/verification."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def seal_value(value: Any) -> str:
    """Digest of a Python value via its canonical JSON encoding."""
    return sha256_hex(canonical_json(value))


def load_sealed(name: str) -> dict:
    """Load a sealed answer document by base name (without extension)."""
    path = SEALED_DIR / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(f"sealed answer document missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def verify_sealed_isolation() -> dict:
    """Confirm the sealed directory is excluded by the engine's containment.

    Returns a small evidence dict. Imports the project registry lazily so this
    module stays import-light and free of cycles.
    """
    from doofus.meta.codeevolve import project_registry

    sealed_protected = project_registry.is_protected_path(SEALED_DIR)
    # A representative sealed file is also covered (overlap, not just equality).
    sample = SEALED_DIR / "calibration.json"
    sample_protected = project_registry.is_protected_path(sample)
    return {
        "sealed_dir": str(SEALED_DIR),
        "sealed_dir_protected": bool(sealed_protected),
        "sealed_file_protected": bool(sample_protected),
        "isolated": bool(sealed_protected and sample_protected),
    }
