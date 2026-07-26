"""Process registry — track protected Doofus runtime PIDs."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from doofus.core.doofus_paths import STATE
from doofus.supervisor.process_singleton import read_singleton_pid, _pid_alive

REGISTRY = STATE / "process_registry.json"
PROTECTED_ROLES = (
    "doofus_runtime_manager",
    "doofus_supervisor",
    "doofus_dashboard",
    "doofus_validation_runner",
)


def _load() -> dict:
    if not REGISTRY.exists():
        return {"roles": {}, "updated_at": None}
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def _save(data: dict) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    REGISTRY.write_text(json.dumps(data, indent=2), encoding="utf-8")


def register_role(role: str, pid: int | None = None) -> None:
    pid = pid or os.getpid()
    data = _load()
    data.setdefault("roles", {})[role] = {"pid": pid, "registered_at": datetime.now(timezone.utc).isoformat()}
    _save(data)


def protected_pids() -> set[int]:
    pids: set[int] = set()
    data = _load()
    for role in PROTECTED_ROLES:
        lock_pid = read_singleton_pid(role)
        if lock_pid and _pid_alive(lock_pid):
            pids.add(lock_pid)
        entry = data.get("roles", {}).get(role)
        if entry and _pid_alive(int(entry.get("pid", 0))):
            pids.add(int(entry["pid"]))
    return pids


def get_registry_snapshot() -> dict:
    data = _load()
    roles = {}
    for role in PROTECTED_ROLES:
        lock_pid = read_singleton_pid(role)
        alive = _pid_alive(lock_pid) if lock_pid else False
        roles[role] = {"lock_pid": lock_pid, "alive": alive}
    return {"roles": roles, "protected_pids": sorted(protected_pids()), "updated_at": data.get("updated_at")}
