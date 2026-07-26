"""Contextual strategy governor using calibrated utility, cost, and risk."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from doofus.metacognition.confidence import clamp_probability
from doofus.metacognition.state import KnowledgeBoundaryState, StrategyAssessment, UncertaintyEstimate


class StrategyContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    difficulty: float = Field(ge=0.0, le=1.0)
    expected_improvability: float = Field(ge=0.0, le=1.0)
    search_saturation: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    transfer_probability: float = Field(ge=0.0, le=1.0)
    uncertainty: UncertaintyEstimate
    boundary: KnowledgeBoundaryState
    regression_rate: float = Field(ge=0.0, le=1.0)
    fitness_noise: float = Field(ge=0.0, le=1.0)


class StrategyDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    strategy_id: str
    algorithm_ids: tuple[str, ...]
    base_gain: float
    information_value: float = Field(ge=0.0, le=1.0)
    compute_cost: float = Field(ge=0.0)
    regression_risk: float = Field(ge=0.0, le=1.0)
    executable: bool


STRATEGIES: tuple[StrategyDefinition, ...] = (
    StrategyDefinition(strategy_id="adaptive_search", algorithm_ids=("trait_shuffle",), base_gain=0.030, information_value=0.25, compute_cost=0.25, regression_risk=0.25, executable=True),
    StrategyDefinition(strategy_id="map_elites_exploration", algorithm_ids=("map_elites_niche", "trait_shuffle"), base_gain=0.025, information_value=0.65, compute_cost=0.50, regression_risk=0.22, executable=True),
    StrategyDefinition(strategy_id="novelty_search", algorithm_ids=("map_elites_niche", "gene_crossover"), base_gain=0.020, information_value=0.80, compute_cost=0.55, regression_risk=0.30, executable=True),
    StrategyDefinition(strategy_id="reflective_prompt_search", algorithm_ids=("gepa_reflective", "model_guided"), base_gain=0.032, information_value=0.55, compute_cost=0.70, regression_risk=0.35, executable=True),
    StrategyDefinition(strategy_id="capsule_recombination", algorithm_ids=("gene_crossover",), base_gain=0.028, information_value=0.35, compute_cost=0.30, regression_risk=0.20, executable=True),
    StrategyDefinition(strategy_id="repair_first", algorithm_ids=("model_guided", "trait_shuffle"), base_gain=0.018, information_value=0.45, compute_cost=0.50, regression_risk=0.18, executable=True),
    StrategyDefinition(strategy_id="adversarial_testing", algorithm_ids=(), base_gain=0.006, information_value=0.90, compute_cost=0.65, regression_risk=0.05, executable=False),
    StrategyDefinition(strategy_id="bayesian_optimization", algorithm_ids=(), base_gain=0.035, information_value=0.60, compute_cost=0.60, regression_risk=0.20, executable=False),
    StrategyDefinition(strategy_id="program_synthesis", algorithm_ids=(), base_gain=0.040, information_value=0.75, compute_cost=0.90, regression_risk=0.45, executable=False),
    StrategyDefinition(strategy_id="architecture_mutation", algorithm_ids=(), base_gain=0.050, information_value=0.75, compute_cost=1.00, regression_risk=0.65, executable=False),
    StrategyDefinition(strategy_id="targeted_parameter_tuning", algorithm_ids=("trait_shuffle",), base_gain=0.022, information_value=0.30, compute_cost=0.20, regression_risk=0.15, executable=True),
    StrategyDefinition(strategy_id="research_first", algorithm_ids=(), base_gain=0.004, information_value=1.00, compute_cost=0.45, regression_risk=0.02, executable=False),
    StrategyDefinition(strategy_id="no_op_observation", algorithm_ids=(), base_gain=0.000, information_value=0.35, compute_cost=0.02, regression_risk=0.00, executable=True),
)


def _contextual_gain(definition: StrategyDefinition, context: StrategyContext) -> float:
    gain = definition.base_gain * context.expected_improvability
    if definition.strategy_id in {"map_elites_exploration", "novelty_search"}:
        gain += context.search_saturation * 0.030
    if definition.strategy_id == "repair_first":
        gain += context.regression_rate * 0.035
    if definition.strategy_id in {"research_first", "adversarial_testing", "no_op_observation"}:
        gain += context.uncertainty.epistemic * 0.020
    if definition.strategy_id == "targeted_parameter_tuning":
        gain += (1.0 - context.difficulty) * 0.015
    return gain


def assess_strategy(definition: StrategyDefinition, context: StrategyContext) -> StrategyAssessment:
    predicted_gain = _contextual_gain(definition, context)
    transfer = clamp_probability(context.transfer_probability * (1.0 - definition.regression_risk * 0.25))
    information_gain = definition.information_value * context.uncertainty.epistemic
    uncertainty_penalty = context.uncertainty.epistemic * (1.0 - definition.information_value) * 0.35
    noise_cost = context.fitness_noise * (0.15 if definition.strategy_id == "no_op_observation" else 0.30)
    utility = (
        predicted_gain * context.confidence * transfer
        + information_gain * 0.08
        - definition.compute_cost * 0.025
        - definition.regression_risk * 0.05
        - uncertainty_penalty * 0.05
        - noise_cost * 0.02
    )
    if context.boundary == KnowledgeBoundaryState.OUTSIDE_AUTHORITY and definition.strategy_id != "no_op_observation":
        utility -= 1.0
    return StrategyAssessment(
        strategy_id=definition.strategy_id,
        algorithm_ids=definition.algorithm_ids,
        predicted_gain=predicted_gain,
        calibrated_confidence=context.confidence,
        transfer_probability=transfer,
        information_gain=information_gain,
        compute_cost=definition.compute_cost,
        regression_risk=definition.regression_risk,
        uncertainty_penalty=uncertainty_penalty,
        utility=utility,
        executable=definition.executable,
    )


def rank_strategies(context: StrategyContext) -> tuple[StrategyAssessment, ...]:
    assessments = [assess_strategy(definition, context) for definition in STRATEGIES]
    assessments.sort(key=lambda assessment: assessment.utility, reverse=True)
    return tuple(assessments)
