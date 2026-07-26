"""Machine-readable schema for held-out benchmark reports."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

SUITE_VERSION = "1.0.0"


class TaskResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    task_id: str
    family: str
    score: float = Field(ge=0.0, le=1.0)
    weight: float = Field(ge=0.0)
    detail: dict


class SuiteReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    suite_version: str
    generated_at: str
    engine_ref: str
    isolation_verified: bool
    task_count: int = Field(ge=0)
    overall_score: float = Field(ge=0.0, le=1.0)
    family_scores: dict[str, float]
    tasks: tuple[TaskResult, ...]
