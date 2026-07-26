"""Aggregate scoring."""
from __future__ import annotations
from doofus.scoring.compounding_score import compounding_score
from doofus.scoring.recursive_learning_score import recursive_learning_score
from doofus.safety.doofus_safety_gate import check_candidate_safety
from doofus.meta.codeevolve.param_overrides import load_score_weights

def score_candidate(candidate: dict, generation: int = 0, prior_best: float = 0.0) -> dict:
    safety = check_candidate_safety(candidate)
    replay = 0.5 + (0.1 if "replay_stability" in candidate.get("traits", []) else 0)
    gen = 0.4 + (0.15 if "generalization_pressure" in candidate.get("traits", []) else 0)
    compound = compounding_score(candidate, prior_best)
    recursive = recursive_learning_score(candidate, generation)
    bloat = 0.1 * max(0, len(candidate.get("traits", [])) - 5)
    proof = 0.45 + (0.15 if "proof_density" in candidate.get("traits", []) else 0)
    w = load_score_weights()
    total = (
        safety["score_safety"] * w["safety"]
        + replay * w["replay"]
        + gen * w["generalization"]
        + compound * w["compounding"]
        + recursive * w["recursive_learning"]
        + proof * w["proof"]
        - bloat
    )
    return {
        "score_total": round(max(0.0, min(1.0, total)), 4),
        "score_safety": safety["score_safety"],
        "score_replay": round(replay, 4),
        "score_generalization": round(gen, 4),
        "score_compounding": round(compound, 4),
        "score_recursive_learning": round(recursive, 4),
        "proof_density_score": round(proof, 4),
        "bloat_penalty": round(bloat, 4),
        "replay_stability_score": round(replay, 4),
    }
