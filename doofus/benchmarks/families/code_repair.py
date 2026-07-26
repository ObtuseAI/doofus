"""Code-repair tasks with hidden, hash-sealed test cases.

Each task ships buggy source that passes the visible public tests but fails on
hidden edge cases. A candidate supplies replacement source per task id; the
harness executes it in an isolated namespace and runs the hidden tests, hashing
each result and comparing to the sealed digest. Score = fraction passed.

Isolation: hidden expected outputs are stored ONLY as SHA-256 digests, so the
sealed file never reveals the answer even if read.
"""
from __future__ import annotations

import json
from typing import Any

from doofus.benchmarks.isolation import TASKS_DIR, load_sealed, seal_value


def load_tasks() -> list[dict]:
    data = json.loads((TASKS_DIR / "code_repair.json").read_text(encoding="utf-8"))
    return list(data["tasks"])


# A conservative execution sandbox: standard builtins, no I/O helpers injected.
# The fixtures are pure numeric/string functions; no network or filesystem.
_SAFE_BUILTINS = {
    "len": len, "range": range, "sorted": sorted, "sum": sum, "min": min,
    "max": max, "abs": abs, "round": round, "int": int, "float": float,
    "str": str, "list": list, "tuple": tuple, "dict": dict, "set": set,
    "enumerate": enumerate, "zip": zip, "map": map, "filter": filter,
    "bool": bool, "all": all, "any": any, "reversed": reversed,
}


def _load_entry(source: str, entry: str):
    namespace: dict[str, Any] = {"__builtins__": _SAFE_BUILTINS}
    exec(compile(source, f"<candidate:{entry}>", "exec"), namespace)  # noqa: S102
    fn = namespace.get(entry)
    if not callable(fn):
        raise ValueError(f"entry {entry!r} not defined by candidate source")
    return fn


def score_task(task: dict, source: str | None = None) -> tuple[float, dict]:
    entry = task["entry"]
    source = source if source is not None else task["source"]
    hidden = load_sealed("code_repair").get(task["task_id"], [])
    if not hidden:
        return 0.0, {"error": "no_hidden_tests"}
    try:
        fn = _load_entry(source, entry)
    except Exception as exc:  # candidate source is untrusted
        return 0.0, {"error": f"load_failed:{type(exc).__name__}", "hidden_total": len(hidden)}
    passed = 0
    errors = 0
    for case in hidden:
        try:
            result = fn(*case["args"])
        except Exception:
            errors += 1
            continue
        if seal_value(result) == case["expected_hash"]:
            passed += 1
    score = passed / len(hidden)
    return round(score, 6), {
        "hidden_passed": passed,
        "hidden_total": len(hidden),
        "hidden_errors": errors,
    }
