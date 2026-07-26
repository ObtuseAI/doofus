"""Bootstrap Doofus source files."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(r"C:\sai-auth-doofus")

FILES: dict[str, str] = {}

def add(rel: str, content: str) -> None:
    FILES[rel] = content

add("doofus/__init__.py", '''"""Doofus — separate local/private autonomous operation."""
__version__ = "1.0.0"
''')

add("doofus/core/doofus_paths.py", '''"""Doofus path constants."""
from __future__ import annotations
from pathlib import Path

ROOT = Path(r"C:\\sai-auth-doofus")
SHARED = Path(r"C:\\Users\\developer\\Desktop\\Shared Folder\\Doofus-Local-Operation")
DUNCE_HANDOFF = Path(r"C:\\Users\\developer\\Desktop\\Shared Folder\\Dunce-Final-Local-Handoff")
ARTIFACTS = ROOT / "artifacts" / "latest"
PROOF = ROOT / "proof_snapshots"
RUNTIME = ROOT / "runtime"
CONTROL = RUNTIME / "control"
LOGS = RUNTIME / "logs"
STATE = RUNTIME / "state"
HEARTBEATS = RUNTIME / "heartbeats"
METRICS_DB = STATE / "doofus_metrics.sqlite"
VENV = ROOT / ".venv_doofus"
RUN_ENABLED = CONTROL / "DOOFUS_RUN.enabled"
STOP_REQUEST = CONTROL / "DOOFUS_STOP.request"
EMERGENCY_STOP = CONTROL / "DOOFUS_EMERGENCY_STOP.request"
''')

add("doofus/core/doofus_config.py", '''"""Doofus configuration from environment."""
from __future__ import annotations
import os
from dataclasses import dataclass

@dataclass
class DoofusConfig:
    model_provider: str = "openrouter"
    model_name: str = "deepseek/deepseek-v4-flash"
    model_temperature: float = 0.6
    max_daily_cost_usd: float = 5.0
    max_model_calls_per_hour: int = 60
    cycle_sleep_seconds: int = 60
    min_cycle_sleep_seconds: int = 10
    dashboard_host: str = "127.0.0.1"
    dashboard_port: int = 8765

    @classmethod
    def from_env(cls) -> "DoofusConfig":
        return cls(
            model_provider=os.environ.get("DOOFUS_MODEL_PROVIDER", "openrouter"),
            model_name=os.environ.get("DOOFUS_MODEL_NAME", "deepseek/deepseek-v4-flash"),
            model_temperature=float(os.environ.get("DOOFUS_MODEL_TEMPERATURE", "0.6")),
            max_daily_cost_usd=float(os.environ.get("DOOFUS_MAX_DAILY_COST_USD", "5")),
            max_model_calls_per_hour=int(os.environ.get("DOOFUS_MAX_MODEL_CALLS_PER_HOUR", "60")),
            cycle_sleep_seconds=int(os.environ.get("DOOFUS_CYCLE_SLEEP_SECONDS", "60")),
        )

    @property
    def openrouter_api_key(self) -> str | None:
        return os.environ.get("OPENROUTER_API_KEY")

    @property
    def model_mode(self) -> str:
        return "live" if self.openrouter_api_key else "dry_run"
''')

add("doofus/core/doofus_events.py", '''"""Doofus event helpers."""
from __future__ import annotations
from datetime import datetime, timezone

def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
''')

add("doofus/core/doofus_state.py", '''"""SQLite metrics schema and helpers."""
from __future__ import annotations
import sqlite3
from pathlib import Path
from doofus.core.doofus_paths import METRICS_DB, STATE
from doofus.core.doofus_events import utc_now

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (run_id TEXT PRIMARY KEY, started_at TEXT, status TEXT);
CREATE TABLE IF NOT EXISTS cycles (cycle_id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, generation INTEGER, created_at TEXT);
CREATE TABLE IF NOT EXISTS candidates (
  candidate_id TEXT PRIMARY KEY, parent_id TEXT, generation INTEGER, traits TEXT,
  mutation_type TEXT, arena_targets TEXT, status TEXT, score_total REAL,
  score_safety REAL, score_replay REAL, score_generalization REAL,
  score_compounding REAL, score_recursive_learning REAL, rejection_reason TEXT,
  promotion_status TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS mutations (id INTEGER PRIMARY KEY AUTOINCREMENT, candidate_id TEXT, mutation_type TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS scores (id INTEGER PRIMARY KEY AUTOINCREMENT, candidate_id TEXT, metric TEXT, value REAL, created_at TEXT);
CREATE TABLE IF NOT EXISTS promotions (id INTEGER PRIMARY KEY AUTOINCREMENT, candidate_id TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS rejections (id INTEGER PRIMARY KEY AUTOINCREMENT, candidate_id TEXT, reason TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS model_calls (id INTEGER PRIMARY KEY AUTOINCREMENT, model TEXT, provider TEXT, tokens_est INTEGER, cost_est REAL, output_hash TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS arena_results (id INTEGER PRIMARY KEY AUTOINCREMENT, candidate_id TEXT, arena TEXT, result TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS safety_events (id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT, detail TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS heartbeats (id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT, detail TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS dashboard_events (id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT, detail TEXT, created_at TEXT);
"""

def init_db(db_path: Path | None = None) -> Path:
    p = db_path or METRICS_DB
    STATE.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p)
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()
    return p

def write_heartbeat(status: str, detail: str = "") -> None:
    init_db()
    conn = sqlite3.connect(METRICS_DB)
    conn.execute("INSERT INTO heartbeats (status, detail, created_at) VALUES (?,?,?)", (status, detail, utc_now()))
    conn.commit()
    conn.close()
''')

add("doofus/safety/on_off_switch.py", '''"""Hard on/off control files."""
from __future__ import annotations
from doofus.core.doofus_paths import RUN_ENABLED, STOP_REQUEST, EMERGENCY_STOP, CONTROL
from doofus.core.doofus_events import utc_now

def ensure_control_dir() -> None:
    CONTROL.mkdir(parents=True, exist_ok=True)

def status() -> dict:
    ensure_control_dir()
    return {
        "run_enabled": RUN_ENABLED.exists(),
        "stop_requested": STOP_REQUEST.exists(),
        "emergency_stop": EMERGENCY_STOP.exists(),
        "may_run": RUN_ENABLED.exists() and not STOP_REQUEST.exists() and not EMERGENCY_STOP.exists(),
        "checked_at": utc_now(),
    }

def start() -> dict:
    ensure_control_dir()
    STOP_REQUEST.unlink(missing_ok=True)
    EMERGENCY_STOP.unlink(missing_ok=True)
    RUN_ENABLED.write_text(f"enabled_at={utc_now()}\\n", encoding="utf-8")
    return status()

def stop() -> dict:
    ensure_control_dir()
    STOP_REQUEST.write_text(f"stop_at={utc_now()}\\n", encoding="utf-8")
    return status()

def emergency_stop() -> dict:
    ensure_control_dir()
    EMERGENCY_STOP.write_text(f"emergency_at={utc_now()}\\n", encoding="utf-8")
    return status()

def clear_emergency() -> None:
    EMERGENCY_STOP.unlink(missing_ok=True)

def check_may_proceed() -> tuple[bool, str]:
    s = status()
    if s["emergency_stop"]:
        return False, "emergency_stop"
    if s["stop_requested"]:
        return False, "stop_requested"
    if not s["run_enabled"]:
        return False, "run_disabled"
    return True, "ok"
''')

add("doofus/safety/budget_guard.py", '''"""Budget and rate guards."""
from __future__ import annotations
import sqlite3
from datetime import datetime, timezone, timedelta
from doofus.core.doofus_config import DoofusConfig
from doofus.core.doofus_paths import METRICS_DB
from doofus.core.doofus_state import init_db

def _conn():
    init_db()
    return sqlite3.connect(METRICS_DB)

def model_calls_last_hour() -> int:
    since = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    c = _conn()
    n = c.execute("SELECT COUNT(*) FROM model_calls WHERE created_at >= ?", (since,)).fetchone()[0]
    c.close()
    return n

def estimated_daily_cost() -> float:
    since = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    c = _conn()
    row = c.execute("SELECT COALESCE(SUM(cost_est),0) FROM model_calls WHERE created_at >= ?", (since,)).fetchone()
    c.close()
    return float(row[0])

def check_budget(cfg: DoofusConfig | None = None) -> dict:
    cfg = cfg or DoofusConfig.from_env()
    calls = model_calls_last_hour()
    cost = estimated_daily_cost()
    ok = calls < cfg.max_model_calls_per_hour and cost < cfg.max_daily_cost_usd
    return {
        "ok": ok,
        "calls_last_hour": calls,
        "max_calls_per_hour": cfg.max_model_calls_per_hour,
        "daily_cost_est": cost,
        "max_daily_cost_usd": cfg.max_daily_cost_usd,
    }
''')

add("doofus/safety/doofus_safety_gate.py", '''"""Safety gate for candidates."""
from __future__ import annotations

FORBIDDEN_TRAITS = frozenset({"wanefall_mutation", "veloren_source_mutation", "chris_mutation", "frankenstein_mutation", "public_deploy", "rom_download", "forced_promotion", "agi_claim", "foundry_proven_claim")

def check_candidate_safety(candidate: dict) -> dict:
    traits = set(candidate.get("traits", []))
    bad = traits & FORBIDDEN_TRAITS
    score = 1.0 if not bad else 0.0
    return {"passes": not bad, "score_safety": score, "violations": sorted(bad)}
''')

add("doofus/model_router/model_call_ledger.py", '''"""Record model calls."""
from __future__ import annotations
import hashlib
import sqlite3
from doofus.core.doofus_paths import METRICS_DB
from doofus.core.doofus_events import utc_now
from doofus.core.doofus_state import init_db

def record_call(model: str, provider: str, output: str, tokens_est: int = 0, cost_est: float = 0.0) -> dict:
    init_db()
    h = hashlib.sha256(output.encode("utf-8")).hexdigest()[:16]
    conn = sqlite3.connect(METRICS_DB)
    conn.execute(
        "INSERT INTO model_calls (model, provider, tokens_est, cost_est, output_hash, created_at) VALUES (?,?,?,?,?,?)",
        (model, provider, tokens_est, cost_est, h, utc_now()),
    )
    conn.commit()
    conn.close()
    return {"output_hash": h, "recorded_at": utc_now()}
''')

add("doofus/model_router/deepseek_v4_flash_adapter.py", '''"""DeepSeek V4 Flash via OpenRouter — no hardcoded credentials."""
from __future__ import annotations
import hashlib
import json
from dataclasses import dataclass
from typing import Any

import requests

from doofus.core.doofus_config import DoofusConfig
from doofus.model_router.model_call_ledger import record_call
from doofus.safety.budget_guard import check_budget

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

@dataclass
class DeepSeekV4FlashAdapter:
    config: DoofusConfig

    @classmethod
    def from_env(cls) -> "DeepSeekV4FlashAdapter":
        return cls(DoofusConfig.from_env())

    def status(self) -> dict[str, Any]:
        return {
            "model": self.config.model_name,
            "provider": self.config.model_provider,
            "mode": self.config.model_mode,
            "temperature": self.config.model_temperature,
            "credentials_present": bool(self.config.openrouter_api_key),
        }

    def propose_mutations(self, context: dict[str, Any]) -> dict[str, Any]:
        budget = check_budget(self.config)
        if not budget["ok"]:
            return {"classification": "DOOFUS_MODEL_BUDGET_BLOCKED", "proposals": [], "budget": budget}
        prompt = json.dumps({"task": "propose_local_mutation_traits", "context": context}, default=str)[:4000]
        if self.config.model_mode == "dry_run":
            out = json.dumps({"proposals": [{"traits": ["replay_stability", "proof_density"], "rationale": "dry_run_stub"}]})
            record_call(self.config.model_name, "dry_run", out, tokens_est=0, cost_est=0.0)
            return {"classification": "DOOFUS_MODEL_DRY_RUN", "proposals": [{"traits": ["replay_stability", "proof_density"]}], "mode": "dry_run"}
        headers = {"Authorization": f"Bearer {self.config.openrouter_api_key}", "Content-Type": "application/json"}
        body = {
            "model": self.config.model_name,
            "temperature": self.config.model_temperature,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 512,
        }
        try:
            r = requests.post(OPENROUTER_URL, headers=headers, json=body, timeout=60)
            r.raise_for_status()
            data = r.json()
            content = data["choices"][0]["message"]["content"]
            record_call(self.config.model_name, self.config.model_provider, content, tokens_est=512, cost_est=0.001)
            return {"classification": "DOOFUS_MODEL_LIVE", "raw": content, "mode": "live"}
        except Exception as exc:
            return {"classification": "DOOFUS_MODEL_ERROR", "error": str(exc), "mode": "live"}
''')

add("doofus/mutation/trait_library.py", '''"""Local trait library."""
TRAITS = [
    "replay_stability", "proof_density", "generalization_pressure", "bloat_guard",
    "arena_agent_arcade", "arena_veloren_bridge", "arena_minetest_stub", "compounding_bias",
]
''')

add("doofus/mutation/candidate_generator.py", '''"""Generate mutation candidates."""
from __future__ import annotations
import hashlib
import random
from doofus.mutation.trait_library import TRAITS
from doofus.core.doofus_events import utc_now

def generate_candidates(generation: int, count: int = 3, seed: int | None = None) -> list[dict]:
    rng = random.Random(seed if seed is not None else generation)
    out = []
    for i in range(count):
        cid = f"DOOFUS_{generation}_{hashlib.sha256(f'{generation}:{i}'.encode()).hexdigest()[:10]}"
        traits = rng.sample(TRAITS, k=rng.randint(2, 4))
        out.append({
            "candidate_id": cid,
            "parent_id": None,
            "generation": generation,
            "traits": traits,
            "mutation_type": "local_trait_shuffle",
            "arena_targets": ["agent_arcade", "dry_replay"],
            "status": "generated",
            "created_at": utc_now(),
        })
    return out
''')

add("doofus/mutation/mutation_engine.py", '''"""Apply mutations to candidates."""
from __future__ import annotations
import random
from doofus.mutation.trait_library import TRAITS

def mutate_candidate(candidate: dict, rng: random.Random | None = None) -> dict:
    rng = rng or random.Random()
    traits = list(candidate.get("traits", []))
    if traits and rng.random() < 0.5:
        traits[rng.randrange(len(traits))] = rng.choice(TRAITS)
    else:
        traits.append(rng.choice(TRAITS))
    child = dict(candidate)
    child["traits"] = sorted(set(traits))
    child["mutation_type"] = "trait_mutation"
    child["parent_id"] = candidate.get("candidate_id")
    return child
''')

add("doofus/mutation/mutation_lineage.py", '''"""Candidate lineage tracking."""
from __future__ import annotations

def build_lineage(candidates: list[dict]) -> dict:
    nodes = {c["candidate_id"]: {"parent": c.get("parent_id"), "generation": c.get("generation")} for c in candidates}
    return {"classification": "DOOFUS_LINEAGE_READY", "nodes": nodes, "count": len(nodes)}
''')

add("doofus/scoring/compounding_score.py", '''"""Local compounding heuristic — not an AGI claim."""
from __future__ import annotations

def compounding_score(candidate: dict, prior_best: float = 0.0) -> float:
    traits = set(candidate.get("traits", []))
    base = 0.3 + 0.1 * len(traits)
    if "compounding_bias" in traits:
        base += 0.15
    if "proof_density" in traits:
        base += 0.1
    return min(1.0, base + max(0.0, prior_best * 0.05))
''')

add("doofus/scoring/recursive_learning_score.py", '''"""Recursive learning heuristic."""
from __future__ import annotations

def recursive_learning_score(candidate: dict, generation: int) -> float:
    traits = set(candidate.get("traits", []))
    base = 0.2 + min(0.4, generation * 0.02)
    if "generalization_pressure" in traits:
        base += 0.15
    if "replay_stability" in traits:
        base += 0.1
    return min(1.0, base)
''')

add("doofus/scoring/rejection_classifier.py", '''"""Classify rejection reasons."""
from __future__ import annotations

def classify_rejection(candidate: dict, scores: dict) -> str | None:
    if scores.get("score_safety", 1) < 0.5:
        return "safety_violation"
    if scores.get("score_total", 0) < 0.35:
        return "low_score"
    if scores.get("bloat_penalty", 0) > 0.5:
        return "bloat"
    if scores.get("score_replay", 0) < 0.4:
        return "replay_failed"
    return None
''')

add("doofus/scoring/score_engine.py", '''"""Aggregate scoring."""
from __future__ import annotations
from doofus.scoring.compounding_score import compounding_score
from doofus.scoring.recursive_learning_score import recursive_learning_score
from doofus.safety.doofus_safety_gate import check_candidate_safety

def score_candidate(candidate: dict, generation: int = 0, prior_best: float = 0.0) -> dict:
    safety = check_candidate_safety(candidate)
    replay = 0.5 + (0.1 if "replay_stability" in candidate.get("traits", []) else 0)
    gen = 0.4 + (0.15 if "generalization_pressure" in candidate.get("traits", []) else 0)
    compound = compounding_score(candidate, prior_best)
    recursive = recursive_learning_score(candidate, generation)
    bloat = 0.1 * max(0, len(candidate.get("traits", [])) - 5)
    proof = 0.45 + (0.15 if "proof_density" in candidate.get("traits", []) else 0)
    total = (safety["score_safety"] * 0.25 + replay * 0.2 + gen * 0.15 + compound * 0.15 + recursive * 0.15 + proof * 0.1) - bloat
    return {
        "score_total": round(max(0.0, min(1.0, total)), 4),
        "score_safety": safety["score_safety"],
        "score_replay": round(replay, 4),
        "score_generalization": round(gen, 4),
        "score_compounding": round(compound, 4),
        "score_recursive_learning": round(recursive, 4),
        "proof_density_score": round(proof, 4),
        "bloat_penalty": round(bloat, 4),
        "replay_stability_score": round(replay, 4),
    }
''')

add("doofus/scoring/promotion_gate.py", '''"""Promotion gate — no forced promotion."""
from __future__ import annotations

PROMOTION_THRESHOLD = 0.72

def evaluate_promotion(candidate: dict, scores: dict, baseline: float = 0.5) -> dict:
    ok = (
        scores.get("score_safety", 0) >= 0.99
        and scores.get("score_replay", 0) >= 0.45
        and scores.get("score_total", 0) >= PROMOTION_THRESHOLD
        and scores.get("score_total", 0) > baseline
        and scores.get("bloat_penalty", 0) <= 0.3
    )
    return {"promoted": ok, "promotion_status": "promoted" if ok else "rejected", "baseline_retained": not ok}
''')

add("doofus/supervisor/doofus_loop_policy.py", '''"""Loop policy constants."""
CYCLE_SLEEP_DEFAULT = 60
CYCLE_SLEEP_MIN = 10
''')

add("doofus/supervisor/doofus_heartbeat.py", '''"""Write heartbeat files and DB."""
from __future__ import annotations
import json
from doofus.core.doofus_paths import HEARTBEATS
from doofus.core.doofus_events import utc_now
from doofus.core.doofus_state import write_heartbeat

def emit_heartbeat(status: str, detail: dict | None = None) -> dict:
    HEARTBEATS.mkdir(parents=True, exist_ok=True)
    doc = {"status": status, "detail": detail or {}, "generated_at": utc_now()}
    path = HEARTBEATS / "latest.json"
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    write_heartbeat(status, json.dumps(detail or {}, default=str)[:500])
    return doc
''')

add("doofus/supervisor/doofus_crash_recovery.py", '''"""Crash recovery stub."""
from __future__ import annotations
import json
from doofus.core.doofus_paths import STATE
from doofus.core.doofus_events import utc_now

CHECKPOINT = STATE / "last_checkpoint.json"

def save_checkpoint(state: dict) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    state["saved_at"] = utc_now()
    CHECKPOINT.write_text(json.dumps(state, indent=2), encoding="utf-8")

def load_checkpoint() -> dict:
    if CHECKPOINT.exists():
        return json.loads(CHECKPOINT.read_text(encoding="utf-8"))
    return {"generation": 0, "baseline_score": 0.5}
''')

add("doofus/supervisor/doofus_loop_runner.py", '''"""Single Doofus cycle runner."""
from __future__ import annotations
import argparse
import sqlite3
import uuid
from doofus.core.doofus_config import DoofusConfig
from doofus.core.doofus_paths import METRICS_DB, ARTIFACTS
from doofus.core.doofus_state import init_db
from doofus.core.doofus_events import utc_now
from doofus.mutation.candidate_generator import generate_candidates
from doofus.mutation.mutation_lineage import build_lineage
from doofus.scoring.score_engine import score_candidate
from doofus.scoring.rejection_classifier import classify_rejection
from doofus.scoring.promotion_gate import evaluate_promotion
from doofus.model_router.deepseek_v4_flash_adapter import DeepSeekV4FlashAdapter
from doofus.safety.on_off_switch import check_may_proceed
from doofus.safety.budget_guard import check_budget
from doofus.supervisor.doofus_crash_recovery import save_checkpoint, load_checkpoint
from doofus.supervisor.doofus_heartbeat import emit_heartbeat

def run_one_cycle(*, dry_run: bool = False) -> dict:
    ok, reason = check_may_proceed()
    if not ok and not dry_run:
        return {"classification": "DOOFUS_CYCLE_SKIPPED", "reason": reason}
    init_db()
    cfg = DoofusConfig.from_env()
    cp = load_checkpoint()
    generation = int(cp.get("generation", 0)) + 1
    baseline = float(cp.get("baseline_score", 0.5))
    run_id = cp.get("run_id") or str(uuid.uuid4())[:12]

    candidates = generate_candidates(generation, count=3)
    adapter = DeepSeekV4FlashAdapter.from_env()
    if check_may_proceed()[0] and check_budget(cfg)["ok"]:
        adapter.propose_mutations({"generation": generation, "baseline": baseline})

    promoted = 0
    rejected = 0
    scored: list[dict] = []
    conn = sqlite3.connect(METRICS_DB)
    for c in candidates:
        if not dry_run and not check_may_proceed()[0]:
            break
        scores = score_candidate(c, generation, baseline)
        c.update(scores)
        rej = classify_rejection(c, scores)
        promo = evaluate_promotion(c, scores, baseline)
        if promo["promoted"]:
            promoted += 1
            baseline = max(baseline, scores["score_total"])
            conn.execute("INSERT INTO promotions (candidate_id, created_at) VALUES (?,?)", (c["candidate_id"], utc_now()))
            c["status"] = "promoted"
        else:
            rejected += 1
            reason = rej or "below_threshold"
            conn.execute("INSERT INTO rejections (candidate_id, reason, created_at) VALUES (?,?,?)", (c["candidate_id"], reason, utc_now()))
            c["status"] = "rejected"
            c["rejection_reason"] = reason
        conn.execute(
            """INSERT OR REPLACE INTO candidates VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (c["candidate_id"], c.get("parent_id"), generation, ",".join(c["traits"]), c["mutation_type"],
             ",".join(c["arena_targets"]), c["status"], scores["score_total"], scores["score_safety"],
             scores["score_replay"], scores["score_generalization"], scores["score_compounding"],
             scores["score_recursive_learning"], c.get("rejection_reason"), promo["promotion_status"], utc_now()),
        )
        scored.append(c)
    conn.execute("INSERT INTO cycles (run_id, generation, created_at) VALUES (?,?,?)", (run_id, generation, utc_now()))
    conn.commit()
    conn.close()

    save_checkpoint({"generation": generation, "baseline_score": baseline, "run_id": run_id})
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    result = {
        "classification": "DOOFUS_CYCLE_COMPLETE",
        "run_id": run_id,
        "generation": generation,
        "candidates": len(scored),
        "promoted": promoted,
        "rejected": rejected,
        "baseline_score": baseline,
        "lineage": build_lineage(scored),
        "model_mode": cfg.model_mode,
        "dry_run": dry_run,
        "generated_at": utc_now(),
    }
    emit_heartbeat("cycle_complete", {"generation": generation, "promoted": promoted, "rejected": rejected})
    return result

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--once", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    doc = run_one_cycle(dry_run=args.dry_run)
    print(doc["classification"], doc.get("generation"), doc.get("promoted"), doc.get("rejected"))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
''')

add("doofus/supervisor/doofus_24_7_supervisor.py", '''"""24/7 supervisor loop."""
from __future__ import annotations
import argparse
import time
from doofus.core.doofus_config import DoofusConfig
from doofus.safety.on_off_switch import check_may_proceed, status
from doofus.supervisor.doofus_loop_runner import run_one_cycle
from doofus.supervisor.doofus_heartbeat import emit_heartbeat
from doofus.core.doofus_paths import EMERGENCY_STOP

def run_supervisor(*, max_cycles: int | None = None) -> int:
    cfg = DoofusConfig.from_env()
    cycles = 0
    emit_heartbeat("supervisor_start", status())
    while True:
        if EMERGENCY_STOP.exists():
            emit_heartbeat("emergency_stop", {})
            break
        may, reason = check_may_proceed()
        if not may:
            emit_heartbeat("supervisor_idle", {"reason": reason})
            time.sleep(cfg.min_cycle_sleep_seconds)
            continue
        run_one_cycle(dry_run=False)
        cycles += 1
        if max_cycles and cycles >= max_cycles:
            break
        time.sleep(max(cfg.min_cycle_sleep_seconds, cfg.cycle_sleep_seconds))
    return 0

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--max-cycles", type=int, default=None)
    args = p.parse_args()
    return run_supervisor(max_cycles=args.max_cycles)

if __name__ == "__main__":
    raise SystemExit(main())
''')

add("doofus/dashboard/dashboard_data.py", '''"""Dashboard data queries."""
from __future__ import annotations
import sqlite3
from doofus.core.doofus_paths import METRICS_DB
from doofus.core.doofus_state import init_db
from doofus.safety.on_off_switch import status as switch_status
from doofus.safety.budget_guard import check_budget
from doofus.core.doofus_config import DoofusConfig
from doofus.supervisor.doofus_crash_recovery import load_checkpoint

def _conn():
    init_db()
    return sqlite3.connect(METRICS_DB)

def summary() -> dict:
    c = _conn()
    cand = c.execute("SELECT COUNT(*) FROM candidates").fetchone()[0]
    prom = c.execute("SELECT COUNT(*) FROM promotions").fetchone()[0]
    rej = c.execute("SELECT COUNT(*) FROM rejections").fetchone()[0]
    mut = c.execute("SELECT COUNT(*) FROM mutations").fetchone()[0]
    mc = c.execute("SELECT COUNT(*) FROM model_calls").fetchone()[0]
    hb = c.execute("SELECT created_at, status FROM heartbeats ORDER BY id DESC LIMIT 1").fetchone()
    c.close()
    cp = load_checkpoint()
    cfg = DoofusConfig.from_env()
    return {
        "switch": switch_status(),
        "budget": check_budget(cfg),
        "candidate_count": cand,
        "promotion_count": prom,
        "rejection_count": rej,
        "mutation_count": mut,
        "model_call_count": mc,
        "generation": cp.get("generation", 0),
        "run_id": cp.get("run_id"),
        "baseline_score": cp.get("baseline_score", 0.5),
        "model_mode": cfg.model_mode,
        "model_name": cfg.model_name,
        "last_heartbeat": {"at": hb[0], "status": hb[1]} if hb else None,
    }

def chart_series() -> dict:
    c = _conn()
    gens = c.execute("SELECT generation, COUNT(*) FROM cycles GROUP BY generation ORDER BY generation").fetchall()
    scores = c.execute("SELECT generation, AVG(score_total), MAX(score_total) FROM candidates GROUP BY generation ORDER BY generation").fetchall()
    rej = c.execute("SELECT reason, COUNT(*) FROM rejections GROUP BY reason").fetchall()
    prom_ts = c.execute("SELECT created_at FROM promotions ORDER BY id").fetchall()
    c.close()
    return {
        "variants_by_generation": [{"generation": g, "count": n} for g, n in gens],
        "avg_score_by_generation": [{"generation": g, "avg": a, "best": b} for g, a, b in scores],
        "rejection_reasons": [{"reason": r, "count": n} for r, n in rej],
        "promotions_over_time": [p[0] for p in prom_ts],
    }
''')

add("doofus/dashboard/dashboard_charts.py", '''"""Plotly chart builders."""
from __future__ import annotations
import plotly.graph_objects as go

def line_chart(title: str, xs: list, ys: list) -> go.Figure:
    fig = go.Figure(data=[go.Scatter(x=xs, y=ys, mode="lines+markers")])
    fig.update_layout(title=title, margin=dict(l=20, r=20, t=40, b=20), height=280)
    return fig

def bar_chart(title: str, labels: list, values: list) -> go.Figure:
    fig = go.Figure(data=[go.Bar(x=labels, y=values)])
    fig.update_layout(title=title, margin=dict(l=20, r=20, t=40, b=20), height=280)
    return fig
''')

add("doofus/dashboard/doofus_dashboard_app.py", '''"""NiceGUI local dashboard — 127.0.0.1 only."""
from __future__ import annotations
from nicegui import ui
from doofus.core.doofus_config import DoofusConfig
from doofus.dashboard.dashboard_data import summary, chart_series
from doofus.dashboard.dashboard_charts import line_chart, bar_chart
from doofus.safety.on_off_switch import start, stop, emergency_stop, status
from doofus.supervisor.doofus_loop_runner import run_one_cycle

cfg = DoofusConfig.from_env()

def refresh_status(label) -> None:
    s = summary()
    label.set_text(
        f"Run: {s.get('run_id')} | Gen: {s.get('generation')} | Candidates: {s['candidate_count']} | "
        f"Promoted: {s['promotion_count']} | Rejected: {s['rejection_count']} | Model: {s['model_mode']}"
    )

def main() -> None:
    ui.label("Doofus Local Operation Dashboard").classes("text-h4")
    status_label = ui.label("Loading...")
    ui.separator()

    with ui.row():
        ui.button("Start Doofus", on_click=lambda: (start(), refresh_status(status_label)))
        ui.button("Stop Doofus", on_click=lambda: (stop(), refresh_status(status_label)))
        ui.button("Emergency Stop", on_click=lambda: (emergency_stop(), refresh_status(status_label)))
        ui.button("Run One Cycle", on_click=lambda: (run_one_cycle(dry_run=True), refresh_status(status_label)))
        ui.button("Refresh", on_click=lambda: refresh_status(status_label))

    ui.separator()
    ui.label("Control switch files only — supervisor obeys safety gates.").classes("text-caption")

    charts = chart_series()
    xs = [d["generation"] for d in charts["avg_score_by_generation"]]
    avgs = [d["avg"] for d in charts["avg_score_by_generation"]]
    bests = [d["best"] for d in charts["avg_score_by_generation"]]
    if xs:
        ui.plotly(line_chart("Average score by generation", xs, avgs))
        ui.plotly(line_chart("Best score by generation", xs, bests))
    rej = charts["rejection_reasons"]
    if rej:
        ui.plotly(bar_chart("Rejection reasons", [r["reason"] for r in rej], [r["count"] for r in rej]))

    ui.separator()
    ui.label(f"Switch: {status()}")
    refresh_status(status_label)

    ui.run(host=cfg.dashboard_host, port=cfg.dashboard_port, reload=False, show=False)

if __name__ in {"__main__", "__mp_main__"}:
    main()
''')

add("doofus/reports/doofus_report_builder.py", '''"""Build Doofus run reports."""
from __future__ import annotations
from doofus.dashboard.dashboard_data import summary, chart_series
from doofus.core.doofus_events import utc_now

def build_latest_run_report() -> dict:
    s = summary()
    return {
        "classification": "DOOFUS_LATEST_RUN_REPORT_READY",
        "label": "doofus_local_operation_ready_with_notes",
        "foundry_proven": False,
        "summary": s,
        "charts": chart_series(),
        "generated_at": utc_now(),
    }
''')

add("doofus/reports/doofus_shared_folder_exporter.py", '''"""Export reports to Shared Folder."""
from __future__ import annotations
import json
from pathlib import Path
from doofus.core.doofus_paths import SHARED
from doofus.reports.doofus_report_builder import build_latest_run_report

DOCS = {
    "DOOFUS-LOCAL-OPERATION-README.md": "# Doofus Local Operation\\n\\nSeparate from frozen Dunce handoff. Local/private only.\\n",
    "DOOFUS-DASHBOARD-START-INSTRUCTIONS.md": "# Dashboard\\n\\n`scripts\\\\doofus_dashboard.ps1` → http://127.0.0.1:8765\\n",
    "DOOFUS-ON-OFF-SWITCH.md": "# On/Off Switch\\n\\nControl files under runtime/control/.\\n",
    "DOOFUS-DEEPSEEK-V4-FLASH-POLICY.md": "# DeepSeek V4 Flash\\n\\nNo hardcoded credentials. dry_run if OPENROUTER_API_KEY absent.\\n",
    "DOOFUS-SAFETY-BOUNDARY.md": "# Safety\\n\\nfoundry_proven=false. No AGI/public claims. No forced promotion.\\n",
    "DOOFUS-DUNCE-SEPARATION.md": "# Dunce Separation\\n\\nDunce handoff package is frozen. Doofus is separate workspace C:\\\\sai-auth-doofus.\\n",
}

def export_shared_folder() -> dict:
    SHARED.mkdir(parents=True, exist_ok=True)
    for name, body in DOCS.items():
        (SHARED / name).write_text(body, encoding="utf-8")
    report = build_latest_run_report()
    (SHARED / "DOOFUS-LATEST-RUN-REPORT.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (SHARED / "DOOFUS-LATEST-RUN-REPORT.md").write_text("# Latest Run\\n\\n" + json.dumps(report["summary"], indent=2), encoding="utf-8")
    (SHARED / "DOOFUS-LOCAL-OPERATION-STATUS.json").write_text(json.dumps(report["summary"], indent=2), encoding="utf-8")
    (SHARED / "DOOFUS-MUTATION-METRICS-SUMMARY.md").write_text("# Metrics\\n\\nSee dashboard charts.\\n", encoding="utf-8")
    final = {"classification": "DOOFUS_LOCAL_OPERATION_FINAL_REPORT", "report": report, "path": str(SHARED)}
    (SHARED / "DOOFUS-LOCAL-OPERATION-FINAL-REPORT.json").write_text(json.dumps(final, indent=2), encoding="utf-8")
    (SHARED / "DOOFUS-LOCAL-OPERATION-FINAL-REPORT.md").write_text("# Doofus Final Report\\n\\nLabel: doofus_local_operation_ready_with_notes\\n", encoding="utf-8")
    return final
''')

for rel, content in FILES.items():
    path = ROOT / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
print("wrote", len(FILES), "modules")
