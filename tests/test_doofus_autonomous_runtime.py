"""Tests for autonomous runtime config."""
from doofus.config.evolution_runtime_config import apply_defaults, evolution_pressure_enabled
from doofus.config.proof_builder_runtime_config import apply_defaults as apply_pb, proof_builder_mode, evidence_based_proof_density


def test_evolution_defaults(monkeypatch):
    monkeypatch.delenv("DOOFUS_EVOLUTION_PRESSURE_MODE", raising=False)
    apply_defaults(force=True)
    assert evolution_pressure_enabled() is True


def test_proof_builder_defaults(monkeypatch):
    monkeypatch.delenv("DOOFUS_PROOF_BUILDER_MODE", raising=False)
    apply_pb(force=True)
    assert proof_builder_mode() is True
    assert evidence_based_proof_density() is True
