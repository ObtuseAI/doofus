"""B1001-B1008 supplemental tests."""
import pytest
from doofus.safety.secret_guard import key_present, assert_no_secret_in_payload, redact_text
from doofus.model_router.model_environment_probe import probe_model_environment
from doofus.model_router.model_secret_redactor import redact_secrets
from doofus.model_router.live_model_smoke import run_live_smoke, PROMPT
from doofus.model_router.deepseek_live_cycle_probe import probe_live_cycle_ready
from doofus.supervisor.live_model_cycle_gate import may_call_model
from doofus.supervisor.doofus_cycle_checkpoint import write_checkpoint, read_checkpoint
from doofus.supervisor.doofus_loop_polisher import POLISH_CHECKS
from doofus.supervisor.windows_task_manifest import task_manifest, SUPERVISOR_TASK
from doofus.scoring.live_candidate_validator import validate_proposal
from doofus.reports.live_cycle_reporter import build_live_cycle_report
from doofus.reports.doofus_24_7_report_builder import build_24_7_report
from doofus.reports.doofus_task_reporter import build_task_report
from doofus.dashboard.dashboard_health_panel import health_panel
from doofus.dashboard.dashboard_control_panel import control_panel
from doofus.dashboard.dashboard_model_panel import model_panel
from doofus.dashboard.dashboard_error_panel import error_panel

def test_secret_guard_redacts():
    out = assert_no_secret_in_payload({"openrouter_api_key_value": "sk-" + ("s" * 32)})
    assert out["openrouter_api_key_value"] == "REDACTED"

def test_model_secret_redactor():
    assert "REDACTED" in redact_secrets("Bearer sk-abcdefghijklmnopqrstuvwxyz123456")

def test_model_environment_probe():
    e = probe_model_environment()
    assert e["openrouter_api_key_value"] == "REDACTED"
    assert "model_name" in e

def test_live_model_smoke_no_leak():
    r = run_live_smoke(max_tokens=16, temperature=0.2)
    blob = str(r)
    assert "sk-" not in blob.lower() or "REDACTED" in blob

def test_live_cycle_probe():
    p = probe_live_cycle_ready()
    assert "ready" in p

def test_may_call_model():
    g = may_call_model(live_requested=False)
    assert "allowed" in g

def test_cycle_checkpoint(tmp_path, monkeypatch):
    from doofus.supervisor import doofus_cycle_checkpoint as cp
    monkeypatch.setattr(cp, "CHECKPOINT", tmp_path / "cp.json")
    write_checkpoint("test", {"x": 1})
    assert read_checkpoint()["stage"] == "test"

def test_polish_checks():
    assert "switch_before_model" in POLISH_CHECKS

def test_windows_task_manifest():
    m = task_manifest()
    assert m["supervisor"]["name"] == SUPERVISOR_TASK
    assert "127.0.0.1" in m["dashboard"]["bind"]

def test_live_candidate_validator_rejects_exec():
    v = validate_proposal('{"cmd": "exec rm -rf"}')
    assert v["valid"] is False

def test_live_cycle_reporter():
    r = build_live_cycle_report({"classification": "TEST"})
    assert r["classification"] == "DOOFUS_LIVE_CYCLE_REPORT"

def test_24_7_report_builder():
    r = build_24_7_report()
    assert r["foundry_proven"] is False

def test_task_reporter():
    r = build_task_report()
    assert r["classification"] == "DOOFUS_TASK_REPORT"

def test_dashboard_panels():
    assert "switch" in health_panel()
    assert control_panel()["writes_files_only"] is True
    assert "environment" in model_panel()
    assert "last_error" in error_panel()

def test_smoke_prompt_harmless():
    assert "commands" in PROMPT.lower()
