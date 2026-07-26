"""Full-time autonomous live runner - outer scheduler, inner one-cycle bounded execution."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from doofus.supervisor import autonomous_run_lease as lease

WORKSPACE = Path(__file__).resolve().parents[2]
LEDGER_PATH = WORKSPACE / "runtime" / "state" / "autonomous_live_runner_ledger.jsonl"
STATUS_PATH = WORKSPACE / "runtime" / "state" / "autonomous_live_runner_status.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def append_ledger(entry: dict[str, Any]) -> None:
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    row = {"timestamp": utc_now(), **entry}
    with LEDGER_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


def write_status(payload: dict[str, Any]) -> None:
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


@dataclass
class RunnerConfig:
    dry_run: bool = True
    once: bool = False
    daemon: bool = False
    operator_approved: bool = False
    provider: str = "openrouter"
    model_alias: str = "deepseekv4flash"
    max_cycles: int = 1
    max_runtime_minutes: int = 30
    max_cost_usd: float = 0.05
    sleep_seconds: int = 60
    require_postlive_certification: bool = True
    proof_builder_first: bool = False
    no_live_if_proof_queue_pending: bool = False
    proof_queue_threshold: int = 5
    proof_safety_critical_threshold: int = 500
    failure_limit: int = 1
    output_dir: Path = field(default_factory=lambda: WORKSPACE / "artifacts" / "doofus" / "openrouter-deepseek-autonomous-live-v1")


class AutonomousLiveRunner:
    def __init__(self, config: RunnerConfig):
        self.config = config
        self.started_at = time.monotonic()
        self.cycles_completed = 0
        self.total_cost_usd = 0.0
        self.failures = 0
        self.session_id = ""
        self.classification = "DOOFUS_AUTONOMOUS_LIVE_RUNNER_STATUS"
        self.runner_state = "RUNNER_IDLE"

    def _autonomous_mode_enabled(self) -> bool:
        from doofus.core.doofus_env_loader import load_doofus_env

        load_doofus_env()
        return os.environ.get("DOOFUS_AUTONOMOUS_LIVE_MODE", "0") == "1"

    def _checkpoint_state(self) -> dict[str, Any]:
        from doofus.runtime.live_db_preflight import inspect_live_db
        from doofus.safety.on_off_switch import status
        from doofus.supervisor.doofus_crash_recovery import load_checkpoint
        from doofus.supervisor.doofus_cycle_checkpoint import read_checkpoint

        ck = load_checkpoint()
        cc = read_checkpoint()
        st = status()
        gen = int(ck.get("generation") or 0)
        pf = inspect_live_db(target_generation=gen + 1)
        return {
            "checkpoint": ck,
            "cycle_checkpoint": cc,
            "stop_flag": st,
            "db_max_generation": inspect_live_db(target_generation=gen).get("db_max_generation"),
            "next_generation": gen + 1 if ck.get("phase") == "complete" else gen,
            "next_gen_rows": pf.get("target_generation_total"),
            "rows_above_checkpoint": pf.get("rows_above_checkpoint", 0),
        }

    def _validate_provider_config(self) -> dict[str, Any]:
        from doofus.model_router.openrouter_live_config import validate_openrouter_live_config

        return validate_openrouter_live_config(dry_run=self.config.dry_run, require_model_id=not self.config.dry_run)

    def _proof_backlog(self) -> dict[str, Any]:
        from doofus.proof.proof_builder_queue import queue_summary
        from doofus.reports.proof_builder_handoff_report import handoff_report

        summary = queue_summary()
        handoff = handoff_report()
        pending = int(summary.get("pending") or 0)
        return {"pending": pending, "summary": summary, "handoff": handoff}

    def _proof_blocks_live(self, proof: dict[str, Any]) -> bool:
        if self.config.no_live_if_proof_queue_pending and proof["pending"] >= self.config.proof_queue_threshold:
            return True
        if proof["pending"] >= self.config.proof_safety_critical_threshold:
            return True
        return False

    def _preflight(self) -> dict[str, Any]:
        from doofus.reports.cycle_orchestrator import run_live_db_preflight, run_nonlive_dry_run_probe
        from doofus.supervisor.checkpoint_baseline import validate_checkpoint, validate_cycle_checkpoint

        state = self._checkpoint_state()
        ck_ok = cc_ok = True
        try:
            validate_checkpoint(state["checkpoint"])
            validate_cycle_checkpoint(state["cycle_checkpoint"])
        except Exception as exc:
            ck_ok = cc_ok = False
            schema_err = str(exc)
        else:
            schema_err = None

        pf = run_live_db_preflight(self.config.output_dir)
        nonlive = run_nonlive_dry_run_probe()
        provider = self._validate_provider_config()
        proof = self._proof_backlog()

        blockers: list[str] = []
        if state["stop_flag"].get("stop_requested") and not self.config.dry_run and not self.config.operator_approved:
            blockers.append("stop_requested")
        if state["next_gen_rows"]:
            blockers.append("rows_above_checkpoint")
        if not ck_ok or not cc_ok:
            blockers.append("checkpoint_schema_invalid")
        if not pf.get("passed"):
            blockers.append("live_db_preflight_failed")
        if nonlive.get("passed") is False:
            blockers.append("nonlive_guard_failed")
        if not provider.get("ready") and not self.config.dry_run:
            blockers.extend(provider.get("blockers") or ["provider_not_ready"])
        if self._proof_blocks_live(proof):
            blockers.append("proof_queue_pending")

        return {
            "passed": not blockers,
            "blockers": blockers,
            "checkpoint_state": state,
            "provider_config": provider,
            "proof_backlog": proof,
            "proof_backlog_monitored_not_blocking": not self.config.no_live_if_proof_queue_pending,
            "live_db_preflight": pf,
            "nonlive_probe": nonlive,
            "schema_error": schema_err,
        }

    def _run_proof_builder_first(self) -> dict[str, Any]:
        script = WORKSPACE / "scripts" / "doofus_proof_builder_backlog_runner.py"
        if not script.exists():
            return {"classification": "PROOF_BUILDER_FIRST_SKIPPED", "reason": "script_missing"}
        proc = subprocess.run(
            [sys.executable, str(script), "--dry-run", "--output-dir", str(self.config.output_dir), "--item-budget", "3"],
            cwd=WORKSPACE,
            capture_output=True,
            text=True,
            timeout=120,
        )
        return {"exit_code": proc.returncode, "stdout_tail": (proc.stdout or "")[-1000:]}

    def _run_one_live_cycle(self) -> dict[str, Any]:
        from doofus.model_router.openrouter_live_config import apply_openrouter_live_env
        from doofus.reports.cycle_orchestrator import run_live_one_cycle

        env = apply_openrouter_live_env(os.environ.copy())
        os.environ.update({k: env[k] for k in env if k.startswith("DOOFUS_") or k.startswith("OPENROUTER_")})
        return run_live_one_cycle(operator_approved=True)

    def _run_postlive_certification(self, *, certified_generation: int) -> dict[str, Any]:
        from doofus.reports.cycle_certification import build_prep_only_launch_packet
        from doofus.reports.cycle_orchestrator import run_nonlive_dry_run_probe
        from doofus.runtime.live_db_preflight import inspect_live_db
        from doofus.safety.on_off_switch import status
        from doofus.supervisor.checkpoint_baseline import validate_checkpoint, validate_cycle_checkpoint
        from doofus.supervisor.controlled_cycle import validate_baseline_for_postlive
        from doofus.supervisor.doofus_crash_recovery import load_checkpoint
        from doofus.supervisor.doofus_cycle_checkpoint import read_checkpoint

        ck = load_checkpoint()
        cc = read_checkpoint()
        st = status()
        gen = int(ck.get("generation") or 0)
        pf = inspect_live_db(target_generation=gen + 1)
        ck_ok = cc_ok = True
        try:
            validate_checkpoint(ck)
            validate_cycle_checkpoint(cc)
        except Exception:
            ck_ok = cc_ok = False

        ok, reasons = validate_baseline_for_postlive(
            checkpoint=ck,
            cycle_checkpoint=cc,
            stop_flag=st,
            db_max_generation=int(pf.get("db_max_generation") or 0),
            certified_generation=certified_generation,
            next_generation_row_count=int(pf.get("target_generation_total") or 0),
            checkpoint_schema_valid=ck_ok,
            cycle_checkpoint_schema_valid=cc_ok,
        )
        nonlive = run_nonlive_dry_run_probe()
        next_gen = certified_generation + 1
        prep = build_prep_only_launch_packet(next_generation=next_gen, certified_generation=certified_generation)
        passed = ok and nonlive.get("passed") is True and gen == certified_generation
        return {
            "classification": "DOOFUS_POSTLIVE_CERTIFICATION_PASS" if passed else "DOOFUS_POSTLIVE_CERTIFICATION_FAIL",
            "passed": passed,
            "certified_generation": certified_generation,
            "next_generation": next_gen,
            "refusal_reasons": reasons,
            "nonlive_probe": nonlive,
            "prep_packet_classification": prep.get("classification"),
            "live_route_invoked": False,
        }

    def _extract_cycle_cost(self, live_result: dict[str, Any]) -> float:
        cycle_out = live_result.get("cycle_output") or {}
        return float(cycle_out.get("cost_observed_usd") or 0.0)

    def _validate_live_cycle(self, live_result: dict[str, Any]) -> tuple[bool, str]:
        if live_result.get("exit_code") != 0:
            return False, "live_cycle_exit_code"
        cycle_out = live_result.get("cycle_output") or {}
        if cycle_out.get("provider_selected") == "cursor":
            return False, "cursor_route_used"
        if cycle_out.get("fallback_used"):
            return False, "fallback_used"
        classification = str(cycle_out.get("classification", ""))
        cycle_class = str(cycle_out.get("cycle_classification", ""))
        if "PASS" not in classification and "PASS" not in cycle_class:
            return False, "cycle_not_pass"
        return True, "ok"

    def _budget_exceeded(self) -> bool:
        elapsed = time.monotonic() - self.started_at
        if elapsed > self.config.max_runtime_minutes * 60:
            return True
        return self.total_cost_usd >= self.config.max_cost_usd

    def _build_payload(self, *, preflight: dict, live_result: dict | None = None, postlive: dict | None = None) -> dict[str, Any]:
        session = lease.read_session()
        return {
            "classification": self.classification,
            "runner_state": self.runner_state,
            "dry_run": self.config.dry_run,
            "daemon": self.config.daemon,
            "once": self.config.once,
            "operator_approved": self.config.operator_approved,
            "provider": self.config.provider,
            "model_alias": self.config.model_alias,
            "max_cycles": self.config.max_cycles,
            "max_runtime_minutes": self.config.max_runtime_minutes,
            "max_cost_usd": self.config.max_cost_usd,
            "cycles_completed": self.cycles_completed,
            "runner_session_id": self.session_id or session.get("runner_session_id"),
            "cycle_lease_id": session.get("cycle_lease_id"),
            "stop_reason": session.get("stop_reason"),
            "stop_observed_source": session.get("stop_observed_source"),
            "last_internal_stop_restore_at": session.get("last_internal_stop_restore_at"),
            "external_stop_requested_at": session.get("external_stop_requested_at"),
            "total_cost_usd": self.total_cost_usd,
            "preflight": preflight,
            "live_result": live_result,
            "postlive_result": postlive,
            "proof_builder_first": self.config.proof_builder_first,
            "autonomous_mode_env": self._autonomous_mode_enabled(),
            "proof_backlog_monitored_not_blocking": not self.config.no_live_if_proof_queue_pending,
        }

    def run(self) -> dict[str, Any]:
        if self.config.daemon and not self.config.operator_approved:
            return {"classification": "DOOFUS_AUTONOMOUS_LIVE_RUNNER_FAIL", "reason": "daemon requires --operator-approved-autonomous-live"}
        if self.config.daemon and not self._autonomous_mode_enabled():
            return {"classification": "DOOFUS_AUTONOMOUS_LIVE_RUNNER_FAIL", "reason": "DOOFUS_AUTONOMOUS_LIVE_MODE=1 required"}
        if self.config.max_cycles < 1:
            return {"classification": "DOOFUS_AUTONOMOUS_LIVE_RUNNER_FAIL", "reason": "max_cycles required"}

        preflight = self._preflight()
        if self.config.dry_run:
            self.classification = (
                "DOOFUS_AUTONOMOUS_LIVE_RUNNER_DRY_RUN_PASS" if preflight.get("passed") else "DOOFUS_AUTONOMOUS_LIVE_RUNNER_FAIL"
            )
            self.runner_state = "RUNNER_DRY_RUN"
            payload = self._build_payload(preflight=preflight)
            write_status(payload)
            append_ledger({"event": "run_complete", "classification": self.classification, "runner_session_id": None})
            return payload

        if not preflight.get("passed"):
            self.classification = "DOOFUS_AUTONOMOUS_LIVE_RUNNER_FAIL"
            payload = self._build_payload(preflight=preflight)
            write_status(payload)
            append_ledger({"event": "run_complete", "classification": self.classification})
            return payload

        self.session_id = lease.new_session_id()
        session = lease.start_session(session_id=self.session_id, max_cycles=self.config.max_cycles)
        append_ledger({"event": "session_start", "runner_session_id": self.session_id, "max_cycles": self.config.max_cycles})
        self.runner_state = "RUNNER_ACTIVE"
        self.classification = "DOOFUS_AUTONOMOUS_LIVE_RUNNER_ACTIVE"

        live_result = None
        postlive = None
        max_iterations = self.config.max_cycles if self.config.daemon else 1

        for cycle_index in range(1, max_iterations + 1):
            halted, halt_reason = lease.external_stop_detected()
            if halted:
                self.classification = "DOOFUS_AUTONOMOUS_LIVE_RUNNER_HALTED_BY_OPERATOR_STOP"
                self.runner_state = "HALTED_BY_OPERATOR_STOP"
                lease.update_session(runner_state=self.runner_state, stop_reason=halt_reason, stop_observed_source="external")
                break

            if self._budget_exceeded():
                self.classification = "DOOFUS_AUTONOMOUS_LIVE_RUNNER_HALTED_BY_BUDGET"
                self.runner_state = "HALTED_BY_BUDGET"
                break

            cycle_lease_id = lease.new_cycle_lease_id(self.session_id, cycle_index)
            lease.update_session(cycle_lease_id=cycle_lease_id, runner_state="CYCLE_RUNNING")
            self.runner_state = "CYCLE_RUNNING"
            write_status(self._build_payload(preflight=preflight))
            append_ledger({"event": "cycle_start", "runner_session_id": self.session_id, "cycle_lease_id": cycle_lease_id})

            preflight = self._preflight()
            if not preflight.get("passed"):
                self.classification = "DOOFUS_AUTONOMOUS_LIVE_RUNNER_FAIL"
                self.runner_state = "HALTED_BY_FAILURE"
                self.failures += 1
                break

            if self.config.proof_builder_first:
                proof_first = self._run_proof_builder_first()
                append_ledger({"event": "proof_builder_first", "cycle_lease_id": cycle_lease_id, "result": proof_first})

            live_result = self._run_one_live_cycle()
            ok, reason = self._validate_live_cycle(live_result)
            if not ok:
                self.classification = "DOOFUS_AUTONOMOUS_LIVE_RUNNER_HALTED_BY_FAILURE"
                self.runner_state = "HALTED_BY_FAILURE"
                append_ledger({"event": "live_cycle", "cycle_lease_id": cycle_lease_id, "result": {"exit_code": live_result.get("exit_code"), "reason": reason}})
                break

            self.cycles_completed += 1
            self.total_cost_usd += self._extract_cycle_cost(live_result)
            lease.record_internal_stop_restore()
            append_ledger({"event": "live_cycle", "cycle_lease_id": cycle_lease_id, "result": {"exit_code": live_result.get("exit_code"), "generation": (live_result.get("cycle_output") or {}).get("generation")}})

            certified_gen = int((live_result.get("cycle_output") or {}).get("generation") or preflight["checkpoint_state"]["checkpoint"].get("generation", 0))
            if self.config.require_postlive_certification:
                self.runner_state = "POSTLIVE_CERTIFYING"
                lease.update_session(runner_state=self.runner_state)
                postlive = self._run_postlive_certification(certified_generation=certified_gen)
                append_ledger({"event": "postlive_certification", "cycle_lease_id": cycle_lease_id, "result": postlive})
                if not postlive.get("passed"):
                    self.classification = "DOOFUS_AUTONOMOUS_LIVE_RUNNER_HALTED_BY_FAILURE"
                    self.runner_state = "HALTED_BY_FAILURE"
                    break

            if self.cycles_completed >= self.config.max_cycles:
                self.classification = "DOOFUS_AUTONOMOUS_LIVE_RUNNER_COMPLETED_MAX_CYCLES"
                self.runner_state = "COMPLETED_MAX_CYCLES"
                break

            if self.config.once or not self.config.daemon:
                self.classification = "DOOFUS_AUTONOMOUS_LIVE_RUNNER_CYCLE_COMPLETED"
                self.runner_state = "CYCLE_COMPLETED_STOP_RESTORED"
                break

            self.runner_state = "SLEEPING_BEFORE_NEXT_CYCLE"
            lease.update_session(runner_state=self.runner_state, cycles_completed=self.cycles_completed)
            write_status(self._build_payload(preflight=preflight, live_result=live_result, postlive=postlive))

            slept = 0
            while slept < self.config.sleep_seconds:
                halted, halt_reason = lease.external_stop_detected()
                if halted:
                    self.classification = "DOOFUS_AUTONOMOUS_LIVE_RUNNER_HALTED_BY_OPERATOR_STOP"
                    self.runner_state = "HALTED_BY_OPERATOR_STOP"
                    lease.update_session(runner_state=self.runner_state, stop_reason=halt_reason)
                    break
                if self._budget_exceeded():
                    self.classification = "DOOFUS_AUTONOMOUS_LIVE_RUNNER_HALTED_BY_BUDGET"
                    self.runner_state = "HALTED_BY_BUDGET"
                    break
                time.sleep(min(5, self.config.sleep_seconds - slept))
                slept += 5
            if self.classification.endswith("_STOP") or self.classification.endswith("_BUDGET"):
                break

        if self.classification == "DOOFUS_AUTONOMOUS_LIVE_RUNNER_ACTIVE" and self.cycles_completed > 0:
            self.classification = "DOOFUS_AUTONOMOUS_LIVE_RUNNER_CYCLE_COMPLETED"
            self.runner_state = "CYCLE_COMPLETED_STOP_RESTORED"

        payload = self._build_payload(preflight=preflight, live_result=live_result, postlive=postlive)
        write_status(payload)
        append_ledger({"event": "run_complete", "classification": self.classification, "runner_session_id": self.session_id, "cycles_completed": self.cycles_completed})
        return payload

    def status(self) -> dict[str, Any]:
        if STATUS_PATH.exists():
            return json.loads(STATUS_PATH.read_text(encoding="utf-8"))
        return {"classification": "DOOFUS_AUTONOMOUS_LIVE_RUNNER_STATUS", "state": "never_run"}
