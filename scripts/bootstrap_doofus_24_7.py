"""Bootstrap B1000-B1008 Doofus 24/7 modules."""
from pathlib import Path

ROOT = Path(r"C:\sai-auth-doofus")

def w(rel: str, body: str) -> None:
    p = ROOT / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body.strip() + "\n", encoding="utf-8")

w("doofus/safety/secret_guard.py", '''
"""Secret guard — never log or persist keys."""
from __future__ import annotations
import os
import re

SECRET_ENV = ("OPENROUTER_API_KEY", "API_KEY", "SECRET")
KEY_PATTERN = re.compile(r"sk-[A-Za-z0-9_\\-]{20,}")

def key_present(name: str = "OPENROUTER_API_KEY") -> bool:
    from doofus.core.doofus_env_loader import load_doofus_env
    load_doofus_env()
    return bool(os.environ.get(name, "").strip())

def redact_text(text: str) -> str:
    from doofus.model_router.model_secret_redactor import redact_secrets
    return redact_secrets(text)

def assert_no_secret_in_payload(payload: dict) -> dict:
    safe = {}
    for k, v in payload.items():
        if any(s in k.upper() for s in ("KEY", "SECRET", "TOKEN", "PASSWORD")):
            safe[k] = "REDACTED"
        elif isinstance(v, str):
            safe[k] = redact_text(v)
        else:
            safe[k] = v
    return safe
''')

w("doofus/model_router/model_secret_redactor.py", '''
"""Redact secrets from strings."""
from __future__ import annotations
import re

_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_\\-]{20,}"),
    re.compile(r"OPENROUTER_API_KEY\\s*=\\s*\\S+", re.I),
)

def redact_secrets(text: str) -> str:
    out = text
    for p in _PATTERNS:
        out = p.sub("REDACTED", out)
    return out
''')

w("doofus/model_router/model_environment_probe.py", '''
"""Probe model environment without exposing secrets."""
from __future__ import annotations
from doofus.core.doofus_config import DoofusConfig
from doofus.safety.secret_guard import key_present

def probe_model_environment() -> dict:
    cfg = DoofusConfig.from_env()
    return {
        "classification": "DOOFUS_MODEL_ENV_PROBE_READY",
        "openrouter_api_key_present": key_present(),
        "openrouter_api_key_value": "REDACTED",
        "model_provider": cfg.model_provider,
        "model_name": cfg.model_name,
        "temperature": cfg.model_temperature,
        "daily_budget_cap": cfg.max_daily_cost_usd,
        "hourly_call_cap": cfg.max_model_calls_per_hour,
        "model_mode": cfg.model_mode,
    }
''')

w("doofus/model_router/live_model_smoke.py", '''
"""Bounded live DeepSeek V4 Flash smoke."""
from __future__ import annotations
import argparse
import json
from doofus.core.doofus_config import DoofusConfig
from doofus.model_router.deepseek_v4_flash_adapter import DeepSeekV4FlashAdapter
from doofus.model_router.model_environment_probe import probe_model_environment
from doofus.model_router.model_secret_redactor import redact_secrets
from doofus.safety.secret_guard import key_present, assert_no_secret_in_payload
from doofus.core.doofus_events import utc_now

PROMPT = (
    "Return one JSON object proposing a toy local-only mutation candidate with fields "
    "candidate_name, trait, safety_note, expected_validation. Do not include commands."
)

def run_live_smoke(*, max_tokens: int = 128, temperature: float = 0.2) -> dict:
    env = probe_model_environment()
    if not env["openrouter_api_key_present"]:
        return {"classification": "B1002_DEEPSEEK_V4_FLASH_LIVE_SMOKE_DRY_RUN_FALLBACK", "provider_call_attempted": False, "model_mode": "dry_run"}
    cfg = DoofusConfig.from_env()
    adapter = DeepSeekV4FlashAdapter(cfg)
    attempted = True
    r = adapter.propose_mutations({"smoke": True, "prompt": PROMPT, "max_tokens": max_tokens, "temperature": temperature})
    succeeded = r.get("classification") == "DOOFUS_MODEL_LIVE"
    parsed = False
    proposal = None
    raw = r.get("raw", "")
    if succeeded and raw:
        try:
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start >= 0 and end > start:
                proposal = json.loads(raw[start:end])
                parsed = isinstance(proposal, dict)
        except json.JSONDecodeError:
            parsed = False
    cls = "B1002_DEEPSEEK_V4_FLASH_LIVE_SMOKE_PASS" if succeeded and parsed else "B1002_DEEPSEEK_V4_FLASH_LIVE_SMOKE_PASS_WITH_NOTES"
    if not env["openrouter_api_key_present"]:
        cls = "B1002_DEEPSEEK_V4_FLASH_LIVE_SMOKE_DRY_RUN_FALLBACK"
    elif not succeeded:
        cls = "B1002_DEEPSEEK_V4_FLASH_LIVE_SMOKE_PASS_WITH_NOTES" if r.get("classification") == "DOOFUS_MODEL_DRY_RUN" else "B1002_DEEPSEEK_V4_FLASH_LIVE_SMOKE_BLOCKED"
    return assert_no_secret_in_payload({
        "classification": cls,
        "provider_call_attempted": attempted,
        "provider_call_succeeded": succeeded,
        "model_name": cfg.model_name,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "output_parsed": parsed,
        "proposal_fields": list(proposal.keys()) if isinstance(proposal, dict) else [],
        "command_executed": False,
        "error": redact_secrets(str(r.get("error", "")))[:200] if not succeeded else "",
        "generated_at": utc_now(),
    })

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--max-tokens", type=int, default=128)
    p.add_argument("--temperature", type=float, default=0.2)
    args = p.parse_args()
    doc = run_live_smoke(max_tokens=args.max_tokens, temperature=args.temperature)
    print(doc["classification"], doc.get("provider_call_succeeded"))
    return 0 if "BLOCKED" not in doc["classification"] else 1

if __name__ == "__main__":
    raise SystemExit(main())
''')

w("doofus/model_router/deepseek_live_cycle_probe.py", '''
"""Probe for live cycle readiness."""
from __future__ import annotations
from doofus.model_router.model_environment_probe import probe_model_environment

def probe_live_cycle_ready() -> dict:
    e = probe_model_environment()
    return {"ready": e["model_mode"] == "live" and e["openrouter_api_key_present"], "environment": e}
''')

w("doofus/supervisor/live_model_cycle_gate.py", '''
"""Gate model calls on switch, budget, rate."""
from __future__ import annotations
from doofus.safety.on_off_switch import check_may_proceed
from doofus.safety.budget_guard import check_budget
from doofus.core.doofus_config import DoofusConfig

def may_call_model(*, live_requested: bool = False) -> dict:
    ok, reason = check_may_proceed()
    cfg = DoofusConfig.from_env()
    budget = check_budget(cfg)
    if not ok:
        return {"allowed": False, "reason": reason, "mode": "blocked"}
    if not budget["ok"]:
        return {"allowed": False, "reason": "budget_or_rate", "mode": "blocked", "budget": budget}
    if live_requested and cfg.model_mode != "live":
        return {"allowed": False, "reason": "no_credentials", "mode": "dry_run"}
    return {"allowed": True, "mode": cfg.model_mode, "budget": budget}
''')

w("doofus/supervisor/doofus_cycle_checkpoint.py", '''
"""Per-stage cycle checkpoints."""
from __future__ import annotations
import json
from doofus.core.doofus_paths import STATE
from doofus.core.doofus_events import utc_now

CHECKPOINT = STATE / "cycle_checkpoint.json"

def write_checkpoint(stage: str, data: dict) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    doc = {"stage": stage, "data": data, "saved_at": utc_now()}
    CHECKPOINT.write_text(json.dumps(doc, indent=2), encoding="utf-8")

def read_checkpoint() -> dict:
    if CHECKPOINT.exists():
        return json.loads(CHECKPOINT.read_text(encoding="utf-8"))
    return {"stage": "none", "data": {}}
''')

w("doofus/supervisor/doofus_loop_polisher.py", '''
"""Loop polish metadata."""
from __future__ import annotations

POLISH_CHECKS = (
    "switch_before_model", "budget_before_model", "rate_before_model",
    "secret_redaction", "proposal_only", "local_validation", "safety_gate",
    "replay_before_promotion", "no_forced_promotion", "checkpoint", "heartbeat",
)
''')

w("doofus/scoring/live_candidate_validator.py", '''
"""Validate model proposals locally — no command execution."""
from __future__ import annotations
import json

FORBIDDEN = ("exec", "eval", "subprocess", "os.system", "rm ", "del ")

def validate_proposal(raw: str) -> dict:
    ok = True
    reason = ""
    proposal = None
    low = raw.lower()
    if any(x in low for x in FORBIDDEN):
        return {"valid": False, "reason": "forbidden_content", "proposal": None}
    try:
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0:
            proposal = json.loads(raw[start:end])
    except json.JSONDecodeError:
        ok = False
        reason = "parse_failed"
    return {"valid": ok and proposal is not None, "reason": reason, "proposal": proposal}
''')

w("doofus/reports/live_cycle_reporter.py", '''
"""Live cycle report snippet."""
from __future__ import annotations
from doofus.core.doofus_events import utc_now

def build_live_cycle_report(cycle: dict) -> dict:
    return {"classification": "DOOFUS_LIVE_CYCLE_REPORT", "cycle": cycle, "generated_at": utc_now()}
''')

w("doofus/supervisor/windows_task_manifest.py", '''
"""Windows scheduled task manifest."""
from __future__ import annotations

SUPERVISOR_TASK = "Doofus-24-7-Supervisor"
DASHBOARD_TASK = "Doofus-Local-Dashboard"
PYTHON = r"C:\\sai-auth-doofus\\.venv_doofus\\Scripts\\python.exe"
WORKDIR = r"C:\\sai-auth-doofus"
SUPERVISOR_ACTION = f'"{PYTHON}" -m doofus.supervisor.doofus_24_7_supervisor'
DASHBOARD_ACTION = f'"{PYTHON}" -m doofus.dashboard.doofus_dashboard_app'

def task_manifest() -> dict:
    return {
        "classification": "DOOFUS_WINDOWS_TASK_MANIFEST_READY",
        "supervisor": {"name": SUPERVISOR_TASK, "action": SUPERVISOR_ACTION, "workdir": WORKDIR},
        "dashboard": {"name": DASHBOARD_TASK, "action": DASHBOARD_ACTION, "workdir": WORKDIR, "bind": "127.0.0.1:8765"},
    }
''')

w("doofus/supervisor/doofus_soak_policy.py", '''
"""24/7 soak limits."""
MAX_SOAK_MODEL_CALLS = 5
MAX_SOAK_COST_USD = 0.25
SOAK_TARGET_SECONDS = 600
SOAK_MIN_SECONDS = 300
''')

w("doofus/dashboard/dashboard_health_panel.py", '''
"""Dashboard health panel data."""
from __future__ import annotations
from doofus.dashboard.dashboard_data import summary

def health_panel() -> dict:
    s = summary()
    return {"heartbeat": s.get("last_heartbeat"), "generation": s.get("generation"), "switch": s.get("switch")}
''')

w("doofus/dashboard/dashboard_control_panel.py", '''
"""Control panel metadata."""
from __future__ import annotations
from doofus.safety.on_off_switch import status

def control_panel() -> dict:
    return {"switch": status(), "writes_files_only": True}
''')

w("doofus/dashboard/dashboard_model_panel.py", '''
"""Model panel data."""
from __future__ import annotations
from doofus.model_router.model_environment_probe import probe_model_environment
from doofus.safety.budget_guard import check_budget
from doofus.core.doofus_config import DoofusConfig

def model_panel() -> dict:
    return {"environment": probe_model_environment(), "budget": check_budget(DoofusConfig.from_env())}
''')

w("doofus/dashboard/dashboard_task_panel.py", '''
"""Task panel — query scheduled task status."""
from __future__ import annotations
import subprocess

def task_panel() -> dict:
    out = {}
    for name in ("Doofus-24-7-Supervisor", "Doofus-Local-Dashboard"):
        r = subprocess.run(["schtasks", "/Query", "/TN", name, "/FO", "LIST"], capture_output=True, text=True)
        out[name] = {"registered": r.returncode == 0, "summary": (r.stdout or r.stderr)[-300:]}
    return out
''')

w("doofus/dashboard/dashboard_error_panel.py", '''
"""Last error from checkpoint/heartbeat."""
from __future__ import annotations
import json
from doofus.core.doofus_paths import HEARTBEATS, STATE

def error_panel() -> dict:
    err = ""
    cp = STATE / "cycle_checkpoint.json"
    if cp.exists():
        err = json.loads(cp.read_text(encoding="utf-8")).get("data", {}).get("last_error", "")
    return {"last_error": err[:500]}
''')

w("doofus/reports/doofus_24_7_report_builder.py", '''
"""Build 24/7 operation report."""
from __future__ import annotations
from doofus.dashboard.dashboard_data import summary
from doofus.model_router.model_environment_probe import probe_model_environment
from doofus.supervisor.windows_task_manifest import task_manifest
from doofus.core.doofus_events import utc_now

def build_24_7_report(ctx: dict | None = None) -> dict:
    ctx = ctx or {}
    return {
        "classification": "DOOFUS_24_7_FINAL_REPORT",
        "label": ctx.get("label", "doofus_24_7_local_operation_ready_with_notes"),
        "foundry_proven": False,
        "summary": summary(),
        "environment": probe_model_environment(),
        "tasks": task_manifest(),
        "bundles": ctx.get("bundles", {}),
        "generated_at": utc_now(),
    }
''')

w("doofus/reports/doofus_task_reporter.py", '''
"""Scheduled task status for reports."""
from __future__ import annotations
from doofus.dashboard.dashboard_task_panel import task_panel

def build_task_report() -> dict:
    return {"classification": "DOOFUS_TASK_REPORT", "tasks": task_panel()}
''')

print("bootstrap modules ok")
