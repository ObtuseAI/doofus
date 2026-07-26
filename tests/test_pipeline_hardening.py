"""Pipeline hardening tests."""
from __future__ import annotations

import json

import pytest

from doofus.core.atomic_json import load_json, save_json
from doofus.evolution.evolution_pressure_mode import apply_pre_promotion_scores
from doofus.meta.codeevolve.ast_allowlist import validate_source
from doofus.meta.codeevolve.param_overrides import load_score_weights, save_score_weights
from doofus.scoring.score_engine import score_candidate


def test_atomic_json_roundtrip(tmp_path):
    p = tmp_path / "state.json"
    save_json(p, {"a": 1})
    assert load_json(p)["a"] == 1


def test_atomic_json_corrupt_recovery(tmp_path):
    p = tmp_path / "state.json"
    p.write_text("{not json", encoding="utf-8")
    assert load_json(p, default={"ok": True}) == {"ok": True}


def test_pre_promotion_scores_runs():
    c = {"candidate_id": "X", "traits": ["replay_stability"], "generation": 1}
    scores = {"score_total": 0.7, "score_safety": 0.99}
    out = apply_pre_promotion_scores(c, scores)
    assert "score_total" in out


def test_score_engine_reads_overrides(tmp_path, monkeypatch):
    from doofus.meta.codeevolve import param_overrides as po
    monkeypatch.setattr(po, "OVERRIDES_FILE", tmp_path / "overrides.json")
    save_score_weights({"safety": 0.3, "replay": 0.2, "generalization": 0.1, "compounding": 0.15, "recursive_learning": 0.15, "proof": 0.1}, fitness=0.5, target_id="test")
    w = load_score_weights()
    assert abs(sum(w.values()) - 1.0) < 0.02


def test_ast_still_blocks_subprocess():
    ok, _ = validate_source("import subprocess")
    assert ok is False
