"""Tests for live response validator."""
from doofus.model_router.live_response_validator import extract_json_object, validate_live_proposal


def test_validate_proposal():
    data = {"candidate_name": "c1", "mutation_trait": "replay_stability", "safety_note": "local only"}
    assert validate_live_proposal(data)["valid"] is True


def test_extract_json():
    assert extract_json_object('{"candidate_name":"x"}')["candidate_name"] == "x"
