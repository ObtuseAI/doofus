"""SQLite metrics schema and helpers."""
from __future__ import annotations
from pathlib import Path
from doofus.core.doofus_paths import METRICS_DB, STATE
from doofus.core.doofus_events import utc_now
from doofus.core.metrics_db import connect_metrics_db

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
CREATE TABLE IF NOT EXISTS arena_results (
  id INTEGER PRIMARY KEY AUTOINCREMENT, candidate_id TEXT, arena TEXT, result TEXT,
  score REAL, steps INTEGER, trace_ref TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS safety_events (id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT, detail TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS heartbeats (id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT, detail TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS dashboard_events (id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT, detail TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS gepa_traces (
  id INTEGER PRIMARY KEY AUTOINCREMENT, cycle_id INTEGER, candidate_id TEXT, prompt_hash TEXT,
  rejection_reason TEXT, score_delta REAL, arena_result TEXT, traits_before TEXT, traits_after TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS gepa_prompt_versions (
  id INTEGER PRIMARY KEY AUTOINCREMENT, prompt_name TEXT, version INTEGER, prompt_hash TEXT,
  prompt_text TEXT, fitness REAL, active INTEGER DEFAULT 0, created_at TEXT);
CREATE TABLE IF NOT EXISTS map_elites_cells (
  id INTEGER PRIMARY KEY AUTOINCREMENT, cell_key TEXT UNIQUE, measure_safety REAL, measure_mutation TEXT,
  measure_arena REAL, fitness REAL, candidate_id TEXT, generation INTEGER, updated_at TEXT);
CREATE TABLE IF NOT EXISTS gep_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT, payload TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS gep_capsules (
  id INTEGER PRIMARY KEY AUTOINCREMENT, capsule_id TEXT UNIQUE, genes TEXT, fitness REAL,
  reuse_count INTEGER DEFAULT 0, created_at TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS codeevolve_generations (
  id INTEGER PRIMARY KEY AUTOINCREMENT, target_module TEXT, generation INTEGER, fitness REAL,
  accepted INTEGER DEFAULT 0, diff_summary TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS model_call_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, generation INTEGER, classification TEXT, provider TEXT,
  transport TEXT, mode TEXT, fallback_from TEXT, proposals_applied INTEGER DEFAULT 0,
  proposal_valid INTEGER DEFAULT 0, cost_est REAL DEFAULT 0, success INTEGER DEFAULT 0, created_at TEXT);
CREATE TABLE IF NOT EXISTS db_health_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT, retries INTEGER DEFAULT 0,
  latency_ms REAL, detail TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS codeevolve_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp_utc TEXT, generation INTEGER, due INTEGER DEFAULT 0,
  attempted INTEGER DEFAULT 0, ran INTEGER DEFAULT 0, skipped INTEGER DEFAULT 0, skip_reason TEXT,
  blocked_by_gate INTEGER DEFAULT 0, gate_name TEXT, gate_details_sanitized TEXT,
  sandbox_enabled INTEGER DEFAULT 0, budget_status TEXT, tier3_status TEXT, proof_density_status TEXT,
  candidates_generated INTEGER DEFAULT 0, candidates_applied INTEGER DEFAULT 0,
  duration_ms REAL DEFAULT 0, error_type TEXT, error_message_sanitized TEXT,
  created_at TEXT);
CREATE TABLE IF NOT EXISTS map_elites_drift_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp_utc TEXT, json_cell_count INTEGER DEFAULT 0,
  sql_cell_count INTEGER DEFAULT 0, drift_count INTEGER DEFAULT 0, missing_in_sql TEXT,
  missing_in_json TEXT, repaired INTEGER DEFAULT 0, repair_reason TEXT,
  unrepaired_reason TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS champion_defense_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp_utc TEXT, generation INTEGER,
  baseline_fitness REAL, best_ever_fitness REAL, best_ever_candidate TEXT,
  latest_tournament_winner TEXT, promotions_since_floor INTEGER DEFAULT 0,
  high_score_rejections_since_floor INTEGER DEFAULT 0, champion_status TEXT,
  replay_required INTEGER DEFAULT 0, replay_passed INTEGER, created_at TEXT);
CREATE TABLE IF NOT EXISTS metacognitive_predictions (
  prediction_id TEXT PRIMARY KEY, target_id TEXT NOT NULL, generation INTEGER NOT NULL,
  strategy_id TEXT NOT NULL, predicted_fitness REAL NOT NULL, interval_low REAL NOT NULL,
  interval_high REAL NOT NULL, probability_non_regression REAL NOT NULL,
  model_confidence REAL NOT NULL, behavioral_confidence REAL NOT NULL,
  evidential_confidence REAL NOT NULL, control_confidence REAL NOT NULL,
  task_difficulty REAL NOT NULL, knowledge_boundary TEXT NOT NULL,
  recommended_action TEXT NOT NULL, recommended_candidates INTEGER NOT NULL,
  search_saturation REAL NOT NULL DEFAULT 0.0, fitness_noise REAL NOT NULL DEFAULT 0.0,
  progress_velocity REAL NOT NULL DEFAULT 0.0, regression_rate REAL NOT NULL DEFAULT 0.0,
  baseline_fitness REAL NOT NULL, actual_fitness REAL, actual_gain REAL,
  actual_non_regression INTEGER, causal_confidence REAL, noise_adjusted_gain REAL,
  resolved_at TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS metacognitive_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT NOT NULL, target_id TEXT NOT NULL,
  generation INTEGER NOT NULL, policy_version TEXT NOT NULL, payload TEXT NOT NULL,
  created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS metacognitive_episodes (
  id INTEGER PRIMARY KEY AUTOINCREMENT, target_id TEXT NOT NULL, generation INTEGER NOT NULL,
  situation TEXT NOT NULL, control_action TEXT NOT NULL, strategy_id TEXT NOT NULL,
  confidence_before REAL NOT NULL, confidence_after REAL NOT NULL, actual_gain REAL NOT NULL,
  success INTEGER NOT NULL, context TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS metacognitive_failures (
  id INTEGER PRIMARY KEY AUTOINCREMENT, target_id TEXT NOT NULL, generation INTEGER NOT NULL,
  failure_type TEXT NOT NULL, detail TEXT NOT NULL, prediction_id TEXT,
  created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS metacognitive_genes (
  gene_id TEXT PRIMARY KEY, gene_type TEXT NOT NULL, context_signature TEXT NOT NULL,
  policy_payload TEXT NOT NULL, fitness REAL NOT NULL, calibration_score REAL NOT NULL,
  holdout_score REAL NOT NULL, active INTEGER NOT NULL DEFAULT 0,
  parent_gene_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS metacognitive_policy_evaluations (
  id INTEGER PRIMARY KEY AUTOINCREMENT, policy_id TEXT NOT NULL, parent_policy_id TEXT,
  episode_count INTEGER NOT NULL, utility_score REAL NOT NULL, brier_score REAL NOT NULL,
  safety_preserved INTEGER NOT NULL, held_out INTEGER NOT NULL,
  promoted INTEGER NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_metacognitive_predictions_target_generation
  ON metacognitive_predictions(target_id, generation);
CREATE INDEX IF NOT EXISTS idx_metacognitive_predictions_resolution
  ON metacognitive_predictions(resolved_at, created_at);
CREATE INDEX IF NOT EXISTS idx_metacognitive_events_generation
  ON metacognitive_events(generation, event_type);
"""

_MIGRATIONS = [
    "ALTER TABLE arena_results ADD COLUMN score REAL",
    "ALTER TABLE arena_results ADD COLUMN steps INTEGER",
    "ALTER TABLE arena_results ADD COLUMN trace_ref TEXT",
]

_MODEL_CALL_EVENT_COLUMNS = {
    "timestamp_utc": "TEXT",
    "run_id": "TEXT",
    "cycle_id": "INTEGER",
    "tournament_count": "INTEGER DEFAULT 0",
    "provider_requested": "TEXT",
    "provider_resolved": "TEXT",
    "model_requested": "TEXT",
    "model_resolved": "TEXT",
    "cursor_agent_cli_authenticated": "INTEGER DEFAULT 0",
    "cursor_api_key_present": "INTEGER DEFAULT 0",
    "prefer_cursor": "INTEGER DEFAULT 0",
    "hybrid_fallback_enabled": "INTEGER DEFAULT 0",
    "mutation_batch_size": "INTEGER DEFAULT 0",
    "model_guided_weight": "REAL DEFAULT 0",
    "attempted": "INTEGER DEFAULT 0",
    "skipped": "INTEGER DEFAULT 0",
    "skip_reason": "TEXT",
    "live": "INTEGER DEFAULT 0",
    "dry_run": "INTEGER DEFAULT 0",
    "fallback_used": "INTEGER DEFAULT 0",
    "fallback_provider": "TEXT",
    "fallback_reason": "TEXT",
    "proposals_requested": "INTEGER DEFAULT 0",
    "proposals_returned": "INTEGER DEFAULT 0",
    "error_type": "TEXT",
    "error_message_sanitized": "TEXT",
    "duration_ms": "REAL DEFAULT 0",
    "estimated_cost": "REAL DEFAULT 0",
    "budget_gate_status": "TEXT",
    "proof_gate_status": "TEXT",
    "tier3_gate_status": "TEXT",
    "detail_json": "TEXT",
}

_METACOGNITIVE_PREDICTION_COLUMNS = {
    "search_saturation": "REAL NOT NULL DEFAULT 0.0",
    "fitness_noise": "REAL NOT NULL DEFAULT 0.0",
    "progress_velocity": "REAL NOT NULL DEFAULT 0.0",
    "regression_rate": "REAL NOT NULL DEFAULT 0.0",
}


def _migrate_arena_results(conn) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(arena_results)")}
    for sql in _MIGRATIONS:
        col = sql.split("ADD COLUMN ")[1].split()[0]
        if col not in cols:
            try:
                conn.execute(sql)
            except Exception:
                pass


def _ensure_columns(conn, table: str, columns: dict[str, str]) -> None:
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    for name, decl in columns.items():
        if name in existing:
            continue
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
        except Exception:
            pass


def init_db(db_path: Path | None = None) -> Path:
    p = db_path or METRICS_DB
    STATE.mkdir(parents=True, exist_ok=True)
    conn = connect_metrics_db(db_path=p)
    try:
        conn.executescript(SCHEMA)
        _migrate_arena_results(conn)
        _ensure_columns(conn, "model_call_events", _MODEL_CALL_EVENT_COLUMNS)
        _ensure_columns(conn, "metacognitive_predictions", _METACOGNITIVE_PREDICTION_COLUMNS)
        conn.commit()
    finally:
        conn.close()
    return p

def write_heartbeat(status: str, detail: str = "") -> None:
    init_db()
    conn = connect_metrics_db()
    conn.execute("INSERT INTO heartbeats (status, detail, created_at) VALUES (?,?,?)", (status, detail, utc_now()))
    conn.commit()
    conn.close()
