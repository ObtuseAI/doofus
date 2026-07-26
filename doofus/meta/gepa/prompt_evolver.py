"""GEPA-style reflective prompt evolution batch."""
from __future__ import annotations

import json
import os

from doofus.config.meta_evolution_config import DEFAULTS, gepa_enabled
from doofus.meta.gepa.prompt_store import get_active, save_version
from doofus.meta.gepa.trace_collector import sample_traces
from doofus.core.doofus_events import utc_now


def _min_traces() -> int:
    return int(os.environ.get("DOOFUS_GEPA_MIN_TRACES", DEFAULTS["DOOFUS_GEPA_MIN_TRACES"]))


def _reflective_mutate(prompt: str, traces: list[dict]) -> str:
    """Local reflective mutation without external API when budget tight."""
    rejections = [t.get("rejection_reason") for t in traces if t.get("rejection_reason")]
    top_reasons = {}
    for r in rejections:
        top_reasons[r] = top_reasons.get(r, 0) + 1
    hints = sorted(top_reasons.items(), key=lambda x: -x[1])[:3]
    hint_text = "; ".join(f"{k}({v})" for k, v in hints) if hints else "none"
    avg_delta = sum(float(t.get("score_delta") or 0) for t in traces) / max(len(traces), 1)
    suffix = (
        f"\n\n[GEPA v-reflect {utc_now()}] Recent rejections: {hint_text}. "
        f"Avg score delta: {avg_delta:.3f}. Favor traits that improve replay and proof_density."
    )
    if suffix.strip() in prompt:
        return prompt + " Emphasize arena_agent_arcade when stagnation detected."
    return prompt + suffix


def run_batch(*, force: bool = False) -> dict:
    if not gepa_enabled():
        return {"classification": "GEPA_SKIPPED", "reason": "disabled"}
    traces = sample_traces(limit=20)
    if len(traces) < _min_traces() and not force:
        return {"classification": "GEPA_BATCH_DEFERRED", "traces": len(traces), "min": _min_traces()}
    current = get_active("mutation")
    promoted = [t for t in traces if float(t.get("score_delta") or 0) > 0]
    fitness = len(promoted) / max(len(traces), 1)
    variants = [_reflective_mutate(current, traces)]
    if traces:
        variants.append(_reflective_mutate(current, traces[:5]))
        variants.append(_reflective_mutate(current, traces[-5:]))
    best = current
    best_fit = fitness
    for v in variants:
        fit = fitness + (0.01 if "arena_agent_arcade" in v else 0)
        if fit > best_fit:
            best_fit = fit
            best = v
    if best != current:
        result = save_version("mutation", best, fitness=best_fit, activate=True)
        return {"classification": "GEPA_BATCH_COMPLETE", "new_version": result, "traces_used": len(traces)}
    return {"classification": "GEPA_BATCH_NO_CHANGE", "traces_used": len(traces), "fitness": fitness}


def build_mutation_context(base_context: dict) -> dict:
    """Enrich model context with active GEPA prompt."""
    from doofus.meta.gepa.prompt_store import get_active
    ctx = dict(base_context)
    ctx["system_prompt"] = get_active("mutation")
    ctx["gepa_active"] = True
    return ctx
