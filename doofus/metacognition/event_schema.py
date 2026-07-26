"""Typed event envelope for metacognitive audit trails."""
from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict


class MetacognitiveEventType(StrEnum):
    PREDICTION_RECORDED = "prediction_recorded"
    CONTROL_RECOMMENDED = "control_recommended"
    CONTROL_AUTHORIZED = "control_authorized"
    CONTROL_BLOCKED = "control_blocked"
    ONLINE_OBSERVATION = "online_observation"
    OUTCOME_EVALUATED = "outcome_evaluated"
    CALIBRATION_UPDATED = "calibration_updated"
    ABSTENTION_RECORDED = "abstention_recorded"
    POLICY_EVALUATED = "policy_evaluated"
    INTEROCEPTION_DIAGNOSIS = "interoception_diagnosis"


class MetacognitiveEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_type: MetacognitiveEventType
    target_id: str
    generation: int
    policy_version: str
    payload: dict[str, Any]
    created_at: str
