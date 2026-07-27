from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from doofus.dumbmoney import (
    FundEvidenceDecision,
    FundEvidenceVerdictV1,
    fund_interop_fixture_bundle,
)

REPO = Path(__file__).resolve().parents[1]
STATIC_FIXTURES = REPO / "doofus" / "dumbmoney" / "interop_fixtures"


def test_fund_interop_has_exact_blunder_wire_fields_and_raw_hashes() -> None:
    bundle = fund_interop_fixture_bundle()
    passport = bundle.alpha_passport.model_dump(mode="json")
    assert set(passport) == {
        "schema",
        "passport_id",
        "strategy_lineage_id",
        "venue",
        "strategy_hash",
        "artifact_hashes",
        "evidence_verdict_hashes",
        "intended_instruments",
        "maximum_loss_cents",
        "evidence_class",
        "created_at",
        "expires_at",
    }
    assert passport["schema"] == "dumbmoney.alpha_passport.v1"
    assert passport["venue"] == "dummy_kalshi"
    assert passport["evidence_class"] == "REPLAY"
    assert len(passport["strategy_hash"]) == 64
    assert not passport["strategy_hash"].startswith("sha256:")
    assert passport["created_at"].endswith("Z")
    assert passport["evidence_verdict_hashes"] == []

    for verdict in bundle.evidence_verdicts:
        wire = verdict.model_dump(mode="json")
        assert set(wire) == {
            "schema",
            "verdict_id",
            "passport_digest",
            "evaluator_id",
            "court",
            "decision",
            "evidence_class",
            "artifact_hashes",
            "reason_codes",
            "effective_trial_count",
            "evaluated_at",
            "expires_at",
        }
        assert wire["schema"] == "dumbmoney.evidence_verdict.v1"
        assert wire["decision"] == "PASS"
        assert wire["passport_digest"] == bundle.alpha_passport.digest
        assert len(wire["evaluator_id"]) == 64
        assert wire["evaluated_at"].endswith("Z")


def test_static_fixtures_are_byte_identical_to_exporter() -> None:
    bundle = fund_interop_fixture_bundle()
    expected = {
        "alpha_passport_v1.json": bundle.alpha_passport.canonical_bytes(),
        **{
            f"evidence_verdict_{verdict.court}_v1.json": verdict.canonical_bytes()
            for verdict in bundle.evidence_verdicts
        },
    }
    assert set(path.name for path in STATIC_FIXTURES.glob("*.json")) == set(expected)
    for name, canonical in expected.items():
        assert (STATIC_FIXTURES / name).read_bytes() == canonical + b"\n"


def test_fund_interop_is_unsigned_and_cannot_grant_authority() -> None:
    bundle = fund_interop_fixture_bundle()
    assert bundle.signed is False
    assert bundle.grants_live_authority is False
    assert bundle.grants_capital_authority is False
    assert all(not hasattr(value, "signature") for value in (bundle.alpha_passport, *bundle.evidence_verdicts))
    assert all(not hasattr(value, "sign") for value in (bundle.alpha_passport, *bundle.evidence_verdicts))


def test_blunder_parse_contract_accepts_static_fixtures_byte_for_byte(tmp_path) -> None:
    blunder_repo = REPO.parent / "blunder-dumbmoney"
    if not (blunder_repo / "blunder" / "fund" / "contracts.py").is_file():
        pytest.skip("sibling Blunder checkout is unavailable")
    script = """
import json
import pathlib
from blunder.fund.contracts import parse_contract

root = pathlib.Path(__import__('sys').argv[1])
for path in sorted(root.glob('*.json')):
    raw = path.read_bytes()
    parsed = parse_contract(json.loads(raw))
    assert parsed.canonical_bytes() + b'\\n' == raw, path
print('BLUNDER_INTEROP_OK')
"""
    environment = {
        **os.environ,
        "PYTHONPATH": str(blunder_repo),
        "PYTHONPYCACHEPREFIX": str(tmp_path / "pycache"),
    }
    completed = subprocess.run(
        (sys.executable, "-c", script, str(STATIC_FIXTURES)),
        env=environment,
        cwd=blunder_repo,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "BLUNDER_INTEROP_OK" in completed.stdout
