"""Tests for the external project registry and bounded external evolver."""
from __future__ import annotations

import sys
from pathlib import Path

from doofus.meta.codeevolve.external_evolver import (
    STEP_INITIAL,
    evolve_project,
    find_numeric_param,
    load_evolve_state,
    perturb_numeric_param,
    run_external_generation,
)
from doofus.meta.codeevolve.project_registry import (
    evaluate_project_fitness,
    external_targets,
    is_protected_path,
    register_project,
    registry_snapshot,
    remove_project,
    resolve_target_module,
    set_project_flag,
    validate_project,
)
from doofus.meta.codeevolve.target_registry import get_target, list_targets

def _make_project_dir(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    root.mkdir(parents=True, exist_ok=True)
    (root / "mod.py").write_text("THRESHOLD = 0.5\nCANDIDATES = 8\n", encoding="utf-8")
    return root


def _project(root: Path, **overrides) -> dict:
    base = {
        "id": "myproj",
        "root": str(root),
        "enabled": True,
        "fitness_command": [sys.executable, "-c", "print(0.75)"],
        "targets": [{"id": "threshold", "module": "mod.py", "param_key": "THRESHOLD"}],
    }
    base.update(overrides)
    return base


def test_validate_and_register_roundtrip(tmp_path):
    root = _make_project_dir(tmp_path)
    ok, reason = validate_project(_project(root))
    assert ok, reason
    result = register_project(_project(root))
    assert result["classification"] == "PROJECT_REGISTERED"
    snap = registry_snapshot()
    assert snap["project_count"] == 1
    assert snap["enabled_count"] == 1
    assert remove_project("myproj") is True
    assert registry_snapshot()["project_count"] == 0


def test_validation_rejects_bad_projects(tmp_path):
    root = _make_project_dir(tmp_path)
    assert validate_project(_project(root, id="doofus"))[1] == "reserved_id"
    assert validate_project(_project(root, id="Bad Id!"))[1] == "invalid_id"
    relative = _project(root)
    relative["root"] = "relative/path"
    assert validate_project(relative)[1] == "root_not_absolute"
    assert validate_project(_project(root, fitness_command="pytest -q"))[1] == "invalid_fitness_command"
    assert validate_project(_project(root, fitness_command=[]))[1] == "invalid_fitness_command"
    bad_target = _project(root, targets=[{"id": "t", "module": str(root / "mod.py")}])
    assert validate_project(bad_target)[1].startswith("invalid_target_module")


def test_protected_roots_rejected():
    assert is_protected_path(Path(r"C:\sai-auth")) is True
    assert is_protected_path(Path(r"C:\sai-auth\anything\nested.py")) is True
    p = _project(Path(r"C:\sai-auth\sub"), id="dunce-clone")
    p["root"] = r"C:\sai-auth\sub"
    assert validate_project(p)[1] == "protected_root"


def test_target_containment(tmp_path):
    root = _make_project_dir(tmp_path)
    (tmp_path / "outside.py").write_text("X = 1\n", encoding="utf-8")
    project = _project(root)
    escaped, reason = resolve_target_module(project, {"id": "esc", "module": "../outside.py"})
    assert escaped is None
    assert reason == "escapes_project_root"
    missing, reason = resolve_target_module(project, {"id": "gone", "module": "nope.py"})
    assert missing is None
    assert reason == "module_missing"
    good, reason = resolve_target_module(project, {"id": "ok", "module": "mod.py"})
    assert good is not None and reason == "ok"


def test_external_targets_only_enabled(tmp_path):
    root = _make_project_dir(tmp_path)
    register_project(_project(root, enabled=False))
    assert external_targets() == []
    set_project_flag("myproj", "enabled", True)
    targets = external_targets()
    assert len(targets) == 1
    assert targets[0]["id"] == "myproj:threshold"
    assert targets[0]["source"] == "external"


def test_target_registry_merges_external(tmp_path, monkeypatch):
    root = _make_project_dir(tmp_path)
    register_project(_project(root))
    builtin_only = list_targets(include_external=False)
    assert all(t["source"] == "builtin" for t in builtin_only)
    merged = list_targets(include_external=True)
    assert len(merged) == len(builtin_only) + 1
    ext = get_target(len(builtin_only), include_external=True)
    assert ext["source"] == "external"
    monkeypatch.setenv("DOOFUS_EXTERNAL_TARGETS_MODE", "0")
    assert len(list_targets()) == len(builtin_only)
    monkeypatch.setenv("DOOFUS_EXTERNAL_TARGETS_MODE", "1")
    assert len(list_targets()) == len(merged)


def test_evaluate_project_fitness_score_line(tmp_path):
    root = _make_project_dir(tmp_path)
    r = evaluate_project_fitness(_project(root))
    assert r["classification"] == "EXTERNAL_FITNESS_OK"
    assert r["fitness"] == 0.75
    fail = evaluate_project_fitness(_project(root, fitness_command=[sys.executable, "-c", "raise SystemExit(3)"]))
    assert fail["classification"] == "EXTERNAL_FITNESS_FAIL"
    assert fail["fitness"] == 0.0
    plain = evaluate_project_fitness(_project(root, fitness_command=[sys.executable, "-c", "print('all tests passed')"]))
    assert plain["fitness"] == 1.0


def test_fitness_env_strips_doofus_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-should-not-leak")
    monkeypatch.setenv("DOOFUS_MODEL_NAME", "should-not-leak")
    root = _make_project_dir(tmp_path)
    probe = (
        "import os; leaked = [k for k in ('OPENROUTER_API_KEY',) if k in os.environ]"
        " or [k for k in os.environ if k.startswith('DOOFUS_')];"
        " print(0.0 if leaked else 1.0)"
    )
    r = evaluate_project_fitness(_project(root, fitness_command=[sys.executable, "-c", probe]))
    assert r["fitness"] == 1.0


def test_fitness_never_reuses_stale_python_bytecode(tmp_path):
    root = _make_project_dir(tmp_path)
    module = root / "value.py"
    module.write_text("FITNESS = 0.1\n", encoding="utf-8")
    command = [sys.executable, "-c", "import value; print(value.FITNESS)"]
    project = _project(root, fitness_command=command)
    assert evaluate_project_fitness(project)["fitness"] == 0.1

    original_stat = module.stat()
    module.write_text("FITNESS = 0.9\n", encoding="utf-8")  # same byte length
    module.touch()
    # Recreate the timestamp/size combination Python normally uses to accept
    # a stale pyc after a rapid mutation.
    import os
    os.utime(module, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    assert evaluate_project_fitness(project)["fitness"] == 0.9


def test_perturb_numeric_param():
    src = "THRESHOLD = 0.5\nCANDIDATES = 8\n"
    assert find_numeric_param(src, "THRESHOLD") == (1, 0.5)
    up, reason = perturb_numeric_param(src, "THRESHOLD", 0.05)
    assert reason == "ok" and "THRESHOLD = 0.525" in up
    down, _ = perturb_numeric_param(src, "THRESHOLD", -0.05)
    assert "THRESHOLD = 0.475" in down
    int_up, _ = perturb_numeric_param(src, "CANDIDATES", 0.05)
    assert "CANDIDATES = 9" in int_up  # minimum step of 1 for small ints
    missing, reason = perturb_numeric_param(src, "NOPE", 0.05)
    assert missing is None and reason == "param_not_found"
    non_numeric, reason = perturb_numeric_param("THRESHOLD = 'hi'\n", "THRESHOLD", 0.05)
    assert non_numeric is None


def test_run_external_generation_measure_only(tmp_path, monkeypatch):
    monkeypatch.setenv("DOOFUS_CODEEVOLVE_AUTO_APPLY", "1")
    root = _make_project_dir(tmp_path)
    register_project(_project(root))  # auto_apply defaults False -> measure only
    target = external_targets()[0]
    before = (root / "mod.py").read_text(encoding="utf-8")
    result = run_external_generation(target, 0)
    assert result["classification"] == "CODEEVOLVE_EXTERNAL_MEASURED"
    assert result["accepted"] is False
    assert (root / "mod.py").read_text(encoding="utf-8") == before


def _distance_fitness(optimum: float) -> list[str]:
    """Fitness peaks at THRESHOLD == optimum; smooth landscape for hill-climbing."""
    return [sys.executable, "-c", (
        "import runpy; d = runpy.run_path('mod.py');"
        f" print(max(0.0, min(1.0, 1 - abs(d['THRESHOLD'] - {optimum}))))"
    )]


def test_hill_climb_toward_optimum(tmp_path, monkeypatch):
    monkeypatch.setenv("DOOFUS_CODEEVOLVE_AUTO_APPLY", "1")
    root = _make_project_dir(tmp_path)  # THRESHOLD starts at 0.5
    register_project(_project(root, auto_apply=True, fitness_command=_distance_fitness(0.6)))

    result = evolve_project("myproj", generations=3)
    assert result["classification"] == "EVOLVE_PROJECT_COMPLETE"
    assert result["accepted"] >= 2  # climbing uphill toward 0.6

    final = find_numeric_param((root / "mod.py").read_text(encoding="utf-8"), "THRESHOLD")
    assert final is not None and final[1] > 0.52  # moved toward the optimum

    ts = load_evolve_state("myproj")["targets"]["myproj:threshold"]
    assert ts["step"] > STEP_INITIAL  # accepted steps grow the step size
    assert ts["best_fitness"] is not None and ts["best_fitness"] > 0.9
    assert ts["accepted_count"] >= 2
    assert len(ts["history"]) == 3


def test_hill_climb_flips_direction_on_reject(tmp_path, monkeypatch):
    monkeypatch.setenv("DOOFUS_CODEEVOLVE_AUTO_APPLY", "1")
    root = _make_project_dir(tmp_path)  # THRESHOLD starts at 0.5
    register_project(_project(root, auto_apply=True, fitness_command=_distance_fitness(0.4)))
    target = external_targets()[0]

    # Optimum is below the start: +5% is downhill -> rejected + rolled back.
    result = run_external_generation(target, 0)
    assert result["accepted"] is False
    assert "THRESHOLD = 0.5" in (root / "mod.py").read_text(encoding="utf-8")
    assert load_evolve_state("myproj")["targets"]["myproj:threshold"]["direction"] == -1

    # Flipped direction goes downhill in value, uphill in fitness -> accepted.
    result = run_external_generation(target, 1)
    assert result["accepted"] is True
    final = find_numeric_param((root / "mod.py").read_text(encoding="utf-8"), "THRESHOLD")
    assert final is not None and final[1] < 0.5


def test_evolve_project_measure_only_and_no_targets(tmp_path, monkeypatch):
    monkeypatch.setenv("DOOFUS_CODEEVOLVE_AUTO_APPLY", "1")
    root = _make_project_dir(tmp_path)
    register_project(_project(root, auto_apply=True, fitness_command=_distance_fitness(0.6)))
    before = (root / "mod.py").read_text(encoding="utf-8")

    result = evolve_project("myproj", generations=2, apply_override=False)
    assert result["classification"] == "EVOLVE_PROJECT_COMPLETE"
    assert result["accepted"] == 0
    assert (root / "mod.py").read_text(encoding="utf-8") == before

    assert evolve_project("ghost")["classification"] == "EVOLVE_PROJECT_NO_TARGETS"


def test_run_external_generation_disabled_project(tmp_path):
    root = _make_project_dir(tmp_path)
    register_project(_project(root))
    target = external_targets()[0]
    set_project_flag("myproj", "enabled", False)
    result = run_external_generation(target, 0)
    assert result["classification"] == "CODEEVOLVE_EXTERNAL_SKIPPED"
