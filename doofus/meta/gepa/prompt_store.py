"""Versioned prompt store for GEPA-evolved prompts."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from doofus.core.atomic_json import _assert_runtime_write_allowed
from doofus.core.doofus_events import utc_now
from doofus.core.doofus_paths import STATE
from doofus.core.metrics_db import metrics_conn

PROMPT_DIR = STATE / "gepa" / "prompts"

DEFAULT_MUTATION_PROMPT = (
    "You are Doofus mutation advisor. Given evolution context (generation, baseline, stagnation, "
    "parent traits), propose JSON with proposals:[{traits:[...], rationale:...}]. "
    "Use only safe local traits: replay_stability, proof_density, generalization_pressure, "
    "arena_agent_arcade, compounding_focus. Never propose network egress or credential traits."
)


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _path(name: str) -> Path:
    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    return PROMPT_DIR / f"{name}.json"


def _load_prompt_file(p: Path) -> dict:
    if not p.exists():
        return {}
    try:
        raw = p.read_text(encoding="utf-8").strip()
        if not raw:
            return {}
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def get_active(name: str = "mutation") -> str:
    p = _path(name)
    data = _load_prompt_file(p)
    if data:
        active = data.get("active_version")
        versions = data.get("versions") or []
        for v in versions:
            if v.get("version") == active:
                return v.get("prompt_text") or DEFAULT_MUTATION_PROMPT
    return DEFAULT_MUTATION_PROMPT


def get_active_hash(name: str = "mutation") -> str:
    return _hash(get_active(name))


def save_version(name: str, prompt_text: str, *, fitness: float = 0.0, activate: bool = False) -> dict:
    p = _path(name)
    data = _load_prompt_file(p)
    if not data:
        data = {"name": name, "versions": [], "active_version": 0}
    version = len(data["versions"]) + 1
    entry = {
        "version": version,
        "prompt_text": prompt_text,
        "prompt_hash": _hash(prompt_text),
        "fitness": fitness,
        "created_at": utc_now(),
    }
    data["versions"].append(entry)
    if activate or fitness >= max((v.get("fitness") or 0) for v in data["versions"]):
        data["active_version"] = version
    _assert_runtime_write_allowed(p)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    try:
        with metrics_conn() as conn:
            conn.execute(
                """INSERT INTO gepa_prompt_versions (prompt_name, version, prompt_hash, prompt_text, fitness, active, created_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (name, version, entry["prompt_hash"], prompt_text[:4000], fitness, 1 if data["active_version"] == version else 0, utc_now()),
            )
    except Exception as exc:
        from doofus.core.pipeline_log import pipeline_warn
        pipeline_warn("gepa_prompt_db", f"version insert failed name={name}", exc=exc)
    return {"name": name, "version": version, "active_version": data["active_version"], "fitness": fitness}


def list_versions(name: str = "mutation") -> list[dict]:
    return _load_prompt_file(_path(name)).get("versions") or []


def snapshot() -> dict:
    return {
        "mutation_prompt_hash": get_active_hash("mutation"),
        "mutation_versions": len(list_versions("mutation")),
        "active_preview": get_active("mutation")[:120] + "...",
    }
