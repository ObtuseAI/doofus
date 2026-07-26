from __future__ import annotations

import pytest
from pydantic import ValidationError

from doofus.evidence_contract import MetricEvidence, ResearchEvidence


def test_evidence_contract_keeps_mutation_authority_local() -> None:
    evidence = ResearchEvidence(
        evidence_id="run-1",
        producer="ObtuseAI/doofus",
        domain="code_parameter_evolution",
        generated_at="2026-07-16T00:00:00+00:00",
        subject_ref="sha256:abc",
        evaluation_ref="heldout-suite:1.0.0",
        isolation_verified=True,
        metrics=(MetricEvidence(name="score", baseline=0.3, candidate=0.4, delta=0.1),),
    )
    assert evidence.mutation_authority == "producer_only"
    with pytest.raises(ValidationError):
        ResearchEvidence(**{**evidence.model_dump(), "mutation_authority": "shared"})
