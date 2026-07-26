"""Tests for codeevolve sandbox."""
from __future__ import annotations

from doofus.meta.codeevolve.ast_allowlist import validate_source
from doofus.meta.codeevolve.sandbox_runner import evaluate_candidate_module
from doofus.meta.codeevolve.rollback_manager import should_rollback, record_baseline_promotion_rate


def test_ast_rejects_subprocess():
    ok, reason = validate_source("import subprocess\nsubprocess.run(['echo'])")
    assert ok is False
    assert "forbidden" in reason


def test_ast_allows_safe_code():
    ok, _ = validate_source("x = 1 + 2\nprint(x)")
    assert ok is True


def test_sandbox_evaluate_safe():
    r = evaluate_candidate_module("x = 42")
    assert r["fitness"] >= 0.0


def test_rollback_threshold():
    record_baseline_promotion_rate(0.2)
    assert should_rollback(0.1, 0.2) is True
    assert should_rollback(0.19, 0.2) is False
