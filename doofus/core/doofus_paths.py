"""Doofus path constants."""
from __future__ import annotations
import os
from pathlib import Path

CANONICAL_ROOT = Path(r"C:\sai-auth-doofus")
CANONICAL_SHARED = Path(r"C:\Users\developer\Desktop\Shared Folder\Doofus-Local-Operation")

ROOT = Path(os.environ.get("DOOFUS_ROOT", str(CANONICAL_ROOT)))
SHARED = Path(os.environ.get("DOOFUS_SHARED", str(CANONICAL_SHARED)))
DUNCE_HANDOFF = Path(r"C:\Users\developer\Desktop\Shared Folder\Dunce-Final-Local-Handoff")
ARTIFACTS = Path(os.environ.get("DOOFUS_ARTIFACTS", str(ROOT / "artifacts" / "latest")))
PROOF = Path(os.environ.get("DOOFUS_PROOF", str(ROOT / "proof_snapshots")))
RUNTIME = Path(os.environ.get("DOOFUS_RUNTIME", str(ROOT / "runtime")))
CONTROL = Path(os.environ.get("DOOFUS_CONTROL", str(RUNTIME / "control")))
LOGS = Path(os.environ.get("DOOFUS_LOGS", str(RUNTIME / "logs")))
STATE = Path(os.environ.get("DOOFUS_STATE", str(RUNTIME / "state")))
HEARTBEATS = Path(os.environ.get("DOOFUS_HEARTBEATS", str(RUNTIME / "heartbeats")))
METRICS_DB = Path(os.environ.get("DOOFUS_METRICS_DB", str(STATE / "doofus_metrics.sqlite")))
VENV = ROOT / ".venv_doofus"
BURN_IN_AUDIT_DIR = ARTIFACTS / "doofus_live_burn_in_promotion_audit"
TWELVE_HOUR_RUN_DIR = ARTIFACTS / "doofus_12_hour_evolution_run"
PROOF_BUILDER_TUNING_DIR = ARTIFACTS / "doofus_proof_builder_shadow_elite_tuning"
FULL_AUTONOMY_DIR = ARTIFACTS / "doofus_fully_autonomous_evolution_loop"
COMPOUNDING_POLISH_DIR = ARTIFACTS / "doofus_autonomous_compounding_polish"
RUNTIME_CLOSURE_DIR = ARTIFACTS / "doofus_windows_runtime_closure"
RUN_ENABLED = Path(os.environ.get("DOOFUS_RUN_ENABLED", str(CONTROL / "DOOFUS_RUN.enabled")))
STOP_REQUEST = Path(os.environ.get("DOOFUS_STOP_REQUEST", str(CONTROL / "DOOFUS_STOP.request")))
EMERGENCY_STOP = Path(os.environ.get("DOOFUS_EMERGENCY_STOP", str(CONTROL / "DOOFUS_EMERGENCY_STOP.request")))

CANONICAL_RUNTIME = CANONICAL_ROOT / "runtime"
CANONICAL_STATE = CANONICAL_RUNTIME / "state"
CANONICAL_METRICS_DB = CANONICAL_STATE / "doofus_metrics.sqlite"
