"""Held-out evolution of monitoring and control thresholds."""
from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from doofus.core import doofus_paths
from doofus.core.atomic_json import load_json, save_json
from doofus.core.doofus_events import utc_now
from doofus.core.metrics_db import metrics_conn
from doofus.metacognition.memory import upsert_metacognitive_gene
from doofus.metacognition.state import ControlAction


class MetaPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    policy_id: str
    parent_policy_id: str
    diversify_saturation_threshold: float = Field(ge=0.50, le=0.98)
    replay_noise_threshold: float = Field(ge=0.20, le=0.90)
    intensify_velocity_threshold: float = Field(ge=0.0, le=0.05)
    narrow_regression_threshold: float = Field(ge=0.20, le=0.90)
    min_control_confidence: float = Field(ge=0.10, le=0.90)
    monitor_every_candidates: int = Field(ge=1, le=16)


class PolicyEpisode(BaseModel):
    model_config = ConfigDict(frozen=True)

    search_saturation: float = Field(ge=0.0, le=1.0)
    fitness_noise: float = Field(ge=0.0, le=1.0)
    progress_velocity: float
    regression_rate: float = Field(ge=0.0, le=1.0)
    control_confidence: float = Field(ge=0.0, le=1.0)
    actual_gain: float
    candidate_count: int = Field(ge=0)


def default_policy() -> MetaPolicy:
    return MetaPolicy(
        policy_id="metacognitive_cortex_v1",
        parent_policy_id="",
        diversify_saturation_threshold=0.65,
        replay_noise_threshold=0.45,
        intensify_velocity_threshold=0.005,
        narrow_regression_threshold=0.50,
        min_control_confidence=0.30,
        monitor_every_candidates=4,
    )


def _policy_file() -> Path:
    return doofus_paths.STATE / "metacognition" / "active_meta_policy.json"


def get_active_meta_policy() -> MetaPolicy:
    raw = load_json(_policy_file(), default={})
    if not isinstance(raw, dict) or not raw:
        return default_policy()
    return MetaPolicy.model_validate(raw)


def _candidate_policies(parent: MetaPolicy) -> tuple[MetaPolicy, ...]:
    changes = (
        ("diversify_saturation_threshold", -0.05),
        ("diversify_saturation_threshold", 0.05),
        ("replay_noise_threshold", -0.05),
        ("replay_noise_threshold", 0.05),
        ("intensify_velocity_threshold", -0.002),
        ("intensify_velocity_threshold", 0.002),
        ("narrow_regression_threshold", -0.05),
        ("narrow_regression_threshold", 0.05),
        ("min_control_confidence", -0.05),
        ("min_control_confidence", 0.05),
        ("monitor_every_candidates", -1),
        ("monitor_every_candidates", 1),
    )
    candidates: list[MetaPolicy] = []
    for index, (field, delta) in enumerate(changes, start=1):
        values = parent.model_dump()
        values[field] = values[field] + delta
        values["policy_id"] = f"{parent.policy_id}_challenger_{index}"
        values["parent_policy_id"] = parent.policy_id
        try:
            candidates.append(MetaPolicy.model_validate(values))
        except ValueError:
            continue
    return tuple(candidates)


def recommend_action(policy: MetaPolicy, episode: PolicyEpisode) -> ControlAction:
    if episode.control_confidence < policy.min_control_confidence:
        return ControlAction.ABSTAIN
    if episode.fitness_noise >= policy.replay_noise_threshold:
        return ControlAction.REPLAY
    if episode.search_saturation >= policy.diversify_saturation_threshold:
        return ControlAction.DIVERSIFY
    if episode.regression_rate >= policy.narrow_regression_threshold:
        return ControlAction.NARROW
    if episode.progress_velocity >= policy.intensify_velocity_threshold:
        return ControlAction.INTENSIFY
    return ControlAction.CONTINUE


def _episode_utility(policy: MetaPolicy, episode: PolicyEpisode) -> float:
    action = recommend_action(policy, episode)
    skip = action in {ControlAction.ABSTAIN, ControlAction.TERMINATE, ControlAction.RESEARCH}
    resource_cost = episode.candidate_count * 0.00025
    if episode.actual_gain > 0.0:
        return -episode.actual_gain if skip else episode.actual_gain - resource_cost
    if skip:
        return abs(episode.actual_gain) + resource_cost
    if action == ControlAction.REPLAY:
        return abs(episode.actual_gain) * 0.25 - resource_cost * 0.5
    return episode.actual_gain - resource_cost


def policy_utility(policy: MetaPolicy, episodes: list[PolicyEpisode]) -> float:
    if not episodes:
        return 0.0
    return sum(_episode_utility(policy, episode) for episode in episodes) / len(episodes)


def _load_episodes(target_id: str) -> list[PolicyEpisode]:
    with metrics_conn() as conn:
        rows = conn.execute(
            """SELECT search_saturation, fitness_noise, progress_velocity, regression_rate,
                      control_confidence, actual_gain, recommended_candidates
               FROM metacognitive_predictions
               WHERE target_id = ? AND resolved_at IS NOT NULL
               ORDER BY created_at ASC""",
            (target_id,),
        ).fetchall()
    return [
        PolicyEpisode(
            search_saturation=float(row[0]),
            fitness_noise=float(row[1]),
            progress_velocity=float(row[2]),
            regression_rate=float(row[3]),
            control_confidence=float(row[4]),
            actual_gain=float(row[5]),
            candidate_count=int(row[6]),
        )
        for row in rows
    ]


def _record_evaluation(
    policy: MetaPolicy,
    episode_count: int,
    utility: float,
    held_out: bool,
    promoted: bool,
    detail: dict[str, object],
) -> None:
    with metrics_conn() as conn:
        conn.execute(
            """INSERT INTO metacognitive_policy_evaluations (
                   policy_id, parent_policy_id, episode_count, utility_score, brier_score,
                   safety_preserved, held_out, promoted, detail, created_at
               ) VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                policy.policy_id,
                policy.parent_policy_id or None,
                episode_count,
                utility,
                0.0,
                1,
                int(held_out),
                int(promoted),
                json.dumps(detail, sort_keys=True, default=str),
                utc_now(),
            ),
        )


def evolve_meta_policy(target_id: str) -> dict[str, object]:
    episodes = _load_episodes(target_id)
    if len(episodes) < 30:
        return {
            "classification": "META_METACOGNITION_INSUFFICIENT_HOLDOUT_EVIDENCE",
            "experimental": True,
            "episode_count": len(episodes),
            "minimum_required": 30,
            "active_policy": get_active_meta_policy().model_dump(),
        }
    split = max(20, int(len(episodes) * 0.80))
    training = episodes[:split]
    holdout = episodes[split:]
    parent = get_active_meta_policy()
    parent_train = policy_utility(parent, training)
    parent_holdout = policy_utility(parent, holdout)
    ranked = sorted(
        _candidate_policies(parent),
        key=lambda candidate: policy_utility(candidate, training),
        reverse=True,
    )
    challenger = ranked[0]
    challenger_train = policy_utility(challenger, training)
    challenger_holdout = policy_utility(challenger, holdout)
    promoted = (
        challenger_train > parent_train + 0.0005
        and challenger_holdout > parent_holdout + 0.0005
    )
    detail = {
        "parent_train_utility": parent_train,
        "parent_holdout_utility": parent_holdout,
        "challenger_train_utility": challenger_train,
        "challenger_holdout_utility": challenger_holdout,
        "safety_surface_mutated": False,
    }
    _record_evaluation(challenger, len(training), challenger_train, False, promoted, detail)
    _record_evaluation(challenger, len(holdout), challenger_holdout, True, promoted, detail)
    if promoted:
        save_json(_policy_file(), challenger.model_dump())
        upsert_metacognitive_gene(
            "meta_policy",
            f"target={target_id}",
            challenger.model_dump(),
            challenger_train,
            0.0,
            challenger_holdout,
            parent.policy_id,
        )
    return {
        "classification": "META_METACOGNITIVE_POLICY_PROMOTED" if promoted else "META_METACOGNITIVE_HOLDOUT_REJECTED",
        "experimental": True,
        "episode_count": len(episodes),
        "parent": parent.model_dump(),
        "challenger": challenger.model_dump(),
        "promoted": promoted,
        "detail": detail,
    }
