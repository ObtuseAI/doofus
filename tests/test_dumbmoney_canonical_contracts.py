from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from doofus.dumbmoney import (
    AlphaPassportV1,
    CanonicalizationError,
    ConsequenceProfileV1,
    ResearchMandateV1,
    alpha_passport_fixture,
    canonical_json,
    canonical_json_bytes,
    content_hash,
    evidence_verdict_fixture,
    export_interoperability_fixtures,
)


def digest(label: str) -> str:
    return content_hash({"label": label})


def test_canonical_json_is_sorted_compact_utf8_and_rejects_nonfinite() -> None:
    left = {"z": "café", "a": [2, 1]}
    right = {"a": [2, 1], "z": "café"}

    assert canonical_json_bytes(left) == canonical_json_bytes(right)
    assert canonical_json(left) == '{"a":[2,1],"z":"café"}'
    assert content_hash(left) == content_hash(right)
    with pytest.raises(CanonicalizationError):
        canonical_json_bytes({"bad": float("nan")})
    with pytest.raises(CanonicalizationError):
        canonical_json_bytes({"unordered": {"a", "b"}})


def test_research_contract_is_frozen_and_has_no_authority() -> None:
    now = datetime(2026, 7, 26, tzinfo=timezone.utc)
    mandate = ResearchMandateV1(
        mandate_id="mandate-1",
        objective="Falsify a candidate.",
        hypotheses=("Candidate improves held-out calibration.",),
        evaluation_protocol_ref=digest("protocol"),
        requested_by="fixture",
        created_at=now,
        expires_at=now + timedelta(days=1),
    )

    assert mandate.schema_id == "dumbmoney.research_mandate.v1"
    assert mandate.broker_authority == "none"
    assert mandate.credential_access == "none"
    assert mandate.capital_signing_authority == "none"
    with pytest.raises(ValidationError):
        mandate.objective = "mutated"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        ResearchMandateV1(
            **{
                **mandate.model_dump(),
                "broker_authority": "place_orders",
            }
        )


def test_consequence_profile_cannot_be_mutated() -> None:
    profile = ConsequenceProfileV1(maximum_external_loss_cents=2_500)
    with pytest.raises(ValidationError):
        profile.maximum_external_loss_cents = 0  # type: ignore[misc]


def test_deterministic_interop_fixture_hashes_and_lowercase_schema_ids(tmp_path) -> None:
    passport = alpha_passport_fixture()
    verdict = evidence_verdict_fixture(passport)

    assert passport.content_hash == (
        "sha256:806a9b7e1845ac654f93584a4513025befa1b5e94a1d126f8a7d4e84c633d89a"
    )
    assert verdict.content_hash == (
        "sha256:942cd2d089bf79edf4ada882a35b2d954bf3ac652f87abdef4c41ee42f95d358"
    )
    assert passport.schema_id == passport.schema_id.lower()
    assert verdict.schema_id == verdict.schema_id.lower()

    paths = export_interoperability_fixtures(tmp_path)
    assert {path.name for path in paths} == {
        "alpha_passport_v1.json",
        "evidence_verdict_v1.json",
        "doofus_interop_bundle_v1.json",
    }
    loaded = json.loads((tmp_path / "alpha_passport_v1.json").read_text(encoding="utf-8"))
    assert AlphaPassportV1.model_validate(loaded) == passport
    assert (tmp_path / "alpha_passport_v1.json").read_bytes().endswith(b"\n")
