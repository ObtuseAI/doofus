"""Sandbox runner for codeevolve fitness evaluation."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from doofus.meta.codeevolve.ast_allowlist import validate_source


def evaluate_candidate_module(source: str, *, timeout: int = 120) -> dict:
    ok, reason = validate_source(source)
    if not ok:
        return {"classification": "CODEEVOLVE_REJECTED", "reason": reason, "fitness": 0.0}
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(source)
        path = f.name
    try:
        proc = subprocess.run(
            [sys.executable, "-c", f"import runpy; runpy.run_path({path!r}, run_name='__sandbox__')"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        fitness = 0.5 if proc.returncode == 0 else 0.1
        return {
            "classification": "CODEEVOLVE_SANDBOX_OK" if proc.returncode == 0 else "CODEEVOLVE_SANDBOX_FAIL",
            "fitness": fitness,
            "stdout": proc.stdout[:500],
            "stderr": proc.stderr[:500],
        }
    except subprocess.TimeoutExpired:
        return {"classification": "CODEEVOLVE_TIMEOUT", "fitness": 0.0}
    finally:
        Path(path).unlink(missing_ok=True)


def evaluate_dry_run_cycles(n: int = 3) -> dict:
    """Fitness via dry-run cycles — mean promotion rate proxy."""
    try:
        from doofus.supervisor.doofus_loop_runner import run_one_cycle
        promoted = 0
        total = 0
        best_delta = 0.0
        for _ in range(n):
            r = run_one_cycle(dry_run=True, live_model_if_available=False)
            promoted += int(r.get("promoted") or 0)
            total += int(r.get("candidates") or 1)
            best_delta = max(best_delta, float(r.get("baseline_score") or 0))
        rate = promoted / max(total, 1)
        fitness = rate + best_delta * 0.01
        return {"classification": "CODEEVOLVE_FITNESS", "fitness": round(fitness, 4), "promotion_rate": rate}
    except Exception as exc:
        return {"classification": "CODEEVOLVE_FITNESS_ERROR", "fitness": 0.0, "error": type(exc).__name__}
