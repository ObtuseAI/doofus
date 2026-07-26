"""External project registry — lets CodeEvolve target other codebases safely."""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

from doofus.benchmarks.isolation import SEALED_DIR as _BENCHMARK_SEALED_DIR
from doofus.core import doofus_paths
from doofus.core.atomic_json import load_json, save_json
from doofus.core.doofus_events import utc_now
from doofus.core.doofus_paths import DUNCE_HANDOFF, STATE

PROJECTS_FILE = Path(os.environ.get("DOOFUS_PROJECTS_FILE", str(STATE / "codeevolve" / "projects.json")))

RESERVED_PROJECT_IDS = {"doofus"}
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

# Operator-protected roots that must never become evolution targets.
# The held-out benchmark answers (doofus/benchmarks/_sealed) are included so the
# evolution engine can never register, resolve, read, or mutate a target that
# overlaps them — keeping the benchmark honestly held out. See
# doofus.benchmarks.isolation for the full rationale.
_STATIC_PROTECTED_ROOTS = (DUNCE_HANDOFF, Path(r"C:\sai-auth"), _BENCHMARK_SEALED_DIR)

DEFAULT_FITNESS_TIMEOUT_SECONDS = 300
MIN_FITNESS_TIMEOUT_SECONDS = 10
MAX_FITNESS_TIMEOUT_SECONDS = 1800

# Doofus-side env never leaks into an external project's fitness process.
_ENV_STRIP_PREFIXES = ("DOOFUS_",)
_ENV_STRIP_KEYS = {"OPENROUTER_API_KEY", "OPENAI_API_KEY", "CURSOR_API_KEY", "CURSOR_AUTH_TOKEN"}


def _protected_roots() -> tuple[Path, ...]:
    return _STATIC_PROTECTED_ROOTS + (doofus_paths.ROOT,)


def _paths_overlap(a: Path, b: Path) -> bool:
    try:
        ra, rb = a.resolve(), b.resolve()
    except OSError:
        ra, rb = a, b
    return ra == rb or ra.is_relative_to(rb) or rb.is_relative_to(ra)


def is_protected_path(path: Path) -> bool:
    return any(_paths_overlap(path, root) for root in _protected_roots())


def validate_project(project: dict) -> tuple[bool, str]:
    if not isinstance(project, dict):
        return False, "not_a_dict"
    pid = project.get("id")
    if not isinstance(pid, str) or not _ID_RE.match(pid):
        return False, "invalid_id"
    if pid in RESERVED_PROJECT_IDS:
        return False, "reserved_id"
    root_raw = project.get("root")
    if not isinstance(root_raw, str) or not root_raw.strip():
        return False, "missing_root"
    root = Path(root_raw)
    if not root.is_absolute():
        return False, "root_not_absolute"
    if is_protected_path(root):
        return False, "protected_root"
    cmd = project.get("fitness_command")
    if not isinstance(cmd, list) or not cmd or not all(isinstance(c, str) and c.strip() for c in cmd):
        return False, "invalid_fitness_command"
    targets = project.get("targets", [])
    if not isinstance(targets, list):
        return False, "invalid_targets"
    seen_targets: set[str] = set()
    for t in targets:
        if not isinstance(t, dict):
            return False, "invalid_target_entry"
        tid = t.get("id")
        if not isinstance(tid, str) or not _ID_RE.match(tid) or tid in seen_targets:
            return False, f"invalid_target_id:{tid}"
        seen_targets.add(tid)
        module = t.get("module")
        if not isinstance(module, str) or not module.strip() or Path(module).is_absolute():
            return False, f"invalid_target_module:{tid}"
        param_key = t.get("param_key")
        if param_key is not None and (not isinstance(param_key, str) or not param_key.isidentifier()):
            return False, f"invalid_param_key:{tid}"
    return True, "ok"


def resolve_target_module(project: dict, target: dict) -> tuple[Path | None, str]:
    """Resolve a target's module path, enforcing containment inside the project root."""
    root = Path(str(project.get("root", "")))
    module = str(target.get("module", ""))
    candidate = (root / module)
    try:
        resolved = candidate.resolve()
        resolved_root = root.resolve()
    except OSError:
        return None, "resolve_failed"
    if not resolved.is_relative_to(resolved_root):
        return None, "escapes_project_root"
    if is_protected_path(resolved):
        return None, "protected_path"
    if not resolved.exists():
        return None, "module_missing"
    return resolved, "ok"


def load_registry() -> dict:
    data = load_json(PROJECTS_FILE, default={"projects": []})
    if not isinstance(data, dict) or not isinstance(data.get("projects"), list):
        return {"projects": []}
    return data


def save_registry(data: dict) -> None:
    save_json(PROJECTS_FILE, data)


def load_projects(*, include_disabled: bool = False) -> list[dict]:
    out = []
    for p in load_registry()["projects"]:
        ok, _ = validate_project(p)
        if not ok:
            continue
        if include_disabled or bool(p.get("enabled")):
            out.append(p)
    return out


def get_project(project_id: str) -> dict | None:
    for p in load_projects(include_disabled=True):
        if p["id"] == project_id:
            return p
    return None


def register_project(project: dict) -> dict:
    ok, reason = validate_project(project)
    if not ok:
        return {"classification": "PROJECT_REJECTED", "reason": reason}
    data = load_registry()
    projects = [p for p in data["projects"] if p.get("id") != project["id"]]
    entry = {
        "id": project["id"],
        "root": str(project["root"]),
        "enabled": bool(project.get("enabled", False)),
        "auto_apply": bool(project.get("auto_apply", False)),
        "fitness_command": list(project["fitness_command"]),
        "fitness_timeout_seconds": int(project.get("fitness_timeout_seconds", DEFAULT_FITNESS_TIMEOUT_SECONDS)),
        "targets": [dict(t) for t in project.get("targets", [])],
        "registered_at": utc_now(),
    }
    projects.append(entry)
    data["projects"] = projects
    save_registry(data)
    return {"classification": "PROJECT_REGISTERED", "project": entry}


def set_project_flag(project_id: str, key: str, value: bool) -> bool:
    if key not in {"enabled", "auto_apply"}:
        return False
    data = load_registry()
    for p in data["projects"]:
        if p.get("id") == project_id:
            p[key] = bool(value)
            save_registry(data)
            return True
    return False


def remove_project(project_id: str) -> bool:
    data = load_registry()
    before = len(data["projects"])
    data["projects"] = [p for p in data["projects"] if p.get("id") != project_id]
    if len(data["projects"]) == before:
        return False
    save_registry(data)
    return True


def external_targets() -> list[dict]:
    """Flattened evolvable targets across enabled external projects."""
    out = []
    for project in load_projects():
        for t in project.get("targets", []):
            module_path, reason = resolve_target_module(project, t)
            if module_path is None:
                continue
            out.append({
                "id": f"{project['id']}:{t['id']}",
                "project_id": project["id"],
                "target_id": t["id"],
                "module_path": module_path,
                "param_key": t.get("param_key"),
                "description": t.get("description", ""),
                "source": "external",
            })
    return out


def project_workspace(project_id: str) -> Path:
    ws = PROJECTS_FILE.parent / "projects" / project_id
    ws.mkdir(parents=True, exist_ok=True)
    return ws


def _fitness_env() -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith(_ENV_STRIP_PREFIXES)}
    for k in _ENV_STRIP_KEYS:
        env.pop(k, None)
    return env


def _parse_score_line(stdout: str) -> float | None:
    """Optional contract: last non-empty stdout line is a 0..1 fitness score."""
    for line in reversed(stdout.strip().splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            v = float(line)
        except ValueError:
            return None
        return v if 0.0 <= v <= 1.0 else None
    return None


def evaluate_project_fitness(project: dict) -> dict:
    """Run the project's fitness command in its root and map the result to 0..1."""
    root = Path(str(project.get("root", "")))
    if not root.is_dir():
        return {"classification": "EXTERNAL_FITNESS_ERROR", "fitness": 0.0, "error": "root_missing"}
    timeout = max(MIN_FITNESS_TIMEOUT_SECONDS, min(
        MAX_FITNESS_TIMEOUT_SECONDS,
        int(project.get("fitness_timeout_seconds", DEFAULT_FITNESS_TIMEOUT_SECONDS)),
    ))
    started = time.perf_counter()
    try:
        # Each evaluation gets a fresh bytecode cache. Rapid rollback/mutation
        # cycles can preserve a file's timestamp and size, causing Python to
        # reuse stale ``.pyc`` code and report a fitness for the wrong source.
        with tempfile.TemporaryDirectory(prefix="doofus-fitness-pycache-") as pycache:
            env = _fitness_env()
            env["PYTHONPYCACHEPREFIX"] = pycache
            proc = subprocess.run(
                list(project["fitness_command"]),
                cwd=str(root),
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
                shell=False,
            )
    except subprocess.TimeoutExpired:
        return {"classification": "EXTERNAL_FITNESS_TIMEOUT", "fitness": 0.0, "timeout_seconds": timeout}
    except (OSError, ValueError) as exc:
        return {"classification": "EXTERNAL_FITNESS_ERROR", "fitness": 0.0, "error": type(exc).__name__}
    duration_ms = (time.perf_counter() - started) * 1000.0
    passed = proc.returncode == 0
    score = _parse_score_line(proc.stdout) if passed else None
    fitness = score if score is not None else (1.0 if passed else 0.0)
    return {
        "classification": "EXTERNAL_FITNESS_OK" if passed else "EXTERNAL_FITNESS_FAIL",
        "fitness": round(float(fitness), 4),
        "returncode": proc.returncode,
        "duration_ms": round(duration_ms, 2),
        "stdout": proc.stdout[-500:],
        "stderr": proc.stderr[-500:],
    }


def registry_snapshot() -> dict:
    projects = load_projects(include_disabled=True)
    return {
        "projects_file": str(PROJECTS_FILE),
        "project_count": len(projects),
        "enabled_count": sum(1 for p in projects if p.get("enabled")),
        "external_target_count": len(external_targets()),
        "projects": [
            {
                "id": p["id"],
                "root": p["root"],
                "enabled": bool(p.get("enabled")),
                "auto_apply": bool(p.get("auto_apply")),
                "targets": [t.get("id") for t in p.get("targets", [])],
            }
            for p in projects
        ],
    }
