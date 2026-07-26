"""Bandit algorithm selection weighted by promotion rate."""
from __future__ import annotations

import random

from doofus.config.cursor_composer_config import cursor_composer_enabled
from doofus.config.meta_evolution_config import aevolve_enabled
from doofus.core.atomic_json import load_json, save_json
from doofus.core.doofus_paths import STATE
from doofus.meta.aevolve.algorithm_registry import ALGORITHMS, apply_env_weight_overrides, list_algorithms, update_weight
from doofus.metacognition.runtime_control import active_algorithm_portfolio

STATS_FILE = STATE / "aevolve" / "algorithm_stats.json"


def _load_stats() -> dict:
    return load_json(STATS_FILE, default={})


def _save_stats(stats: dict) -> None:
    save_json(STATS_FILE, stats)


def _restore_weights_from_stats(stats: dict) -> None:
    for algo, s in stats.items():
        if algo in ALGORITHMS and "weight" in s:
            update_weight(algo, float(s["weight"]))


def _ensure_weights_loaded() -> None:
    stats = _load_stats()
    if stats:
        _restore_weights_from_stats(stats)
    if cursor_composer_enabled():
        apply_env_weight_overrides()


def record_outcome(algorithm_id: str, *, promoted: bool) -> None:
    stats = _load_stats()
    s = stats.setdefault(algorithm_id, {"trials": 0, "promotions": 0, "weight": ALGORITHMS.get(algorithm_id, {}).get("weight", 1.0)})
    s["trials"] += 1
    if promoted:
        s["promotions"] += 1
    rate = s["promotions"] / max(s["trials"], 1)
    weight = 0.3 + rate * 2.0
    update_weight(algorithm_id, weight)
    s["weight"] = weight
    _save_stats(stats)


def select_algorithm(rng: random.Random | None = None) -> str:
    if not aevolve_enabled():
        return "trait_shuffle"
    _ensure_weights_loaded()
    rng = rng or random.Random()
    algos = list_algorithms()
    weights = [ALGORITHMS[a]["weight"] for a in algos]
    total = sum(weights)
    r = rng.random() * total
    acc = 0.0
    for a, w in zip(algos, weights):
        acc += w
        if r <= acc:
            return a
    return algos[0]


def select_algorithms_for_cycle(count: int, seed: int | None = None) -> list[str]:
    rng = random.Random(seed)
    portfolio = {
        algorithm_id: weight
        for algorithm_id, weight in active_algorithm_portfolio().items()
        if algorithm_id in ALGORITHMS and weight > 0.0
    }
    if portfolio:
        algorithms = list(portfolio)
        weights = [portfolio[algorithm_id] for algorithm_id in algorithms]
        return rng.choices(algorithms, weights=weights, k=count)
    return [select_algorithm(rng) for _ in range(count)]


def get_snapshot() -> dict:
    return {"algorithms": ALGORITHMS, "stats": _load_stats()}
