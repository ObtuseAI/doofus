"""True live DeepSeek V4 Flash proof via OpenRouter."""
from __future__ import annotations

import argparse
import json

from doofus.core.doofus_config import DoofusConfig
from doofus.model_router.deepseek_v4_flash_adapter import DeepSeekV4FlashAdapter
from doofus.model_router.live_model_proof_ledger import record_live_proof
from doofus.model_router.live_response_validator import extract_json_object, validate_live_proposal
from doofus.model_router.openrouter_auth_config import ensure_auth_loaded
from doofus.model_router.openrouter_auth_repair_probe import run_repair_probe
from doofus.safety.secret_guard import assert_no_secret_in_payload

PROOF_PROMPT = (
    "Return one JSON object only. Propose one safe local-only Doofus mutation candidate with fields "
    "candidate_name, mutation_trait, expected_metric, safety_note, validation_plan. "
    "Do not include shell commands. Do not include file paths. Do not request secrets."
)


def run_live_proof(*, max_tokens: int = 160, temperature: float = 0.2) -> dict:
    ensure_auth_loaded()
    repair = run_repair_probe()
    if repair.get("provider_auth") != "ok":
        out = {
            "classification": "B1044_TRUE_LIVE_DEEPSEEK_PROOF_AUTH_BLOCKED",
            "provider_auth": repair.get("provider_auth"),
            "winning_source": repair.get("winning_source"),
            "repair_probe": repair.get("classification"),
        }
        record_live_proof(out)
        return assert_no_secret_in_payload(out)

    adapter = DeepSeekV4FlashAdapter.from_env()
    result = adapter.propose_mutations({
        "prompt": PROOF_PROMPT,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "generation": 0,
        "baseline": 0.5,
    })
    cfg = DoofusConfig.from_env()
    parsed = extract_json_object(result.get("raw", "") or "")
    validation = validate_live_proposal(parsed)

    classification = "B1044_TRUE_LIVE_DEEPSEEK_PROOF_PASS"
    if result.get("classification") != "DOOFUS_MODEL_LIVE":
        classification = "B1044_TRUE_LIVE_DEEPSEEK_PROOF_MODEL_BLOCKED"
    elif not validation.get("valid"):
        classification = "B1044_TRUE_LIVE_DEEPSEEK_PROOF_PASS_WITH_NOTES"

    out = assert_no_secret_in_payload({
        "classification": classification,
        "provider_auth": "ok",
        "model_name": cfg.model_name,
        "model_result_classification": result.get("classification"),
        "tokens_est": result.get("tokens_est"),
        "cost_est": result.get("cost_est"),
        "proposal_valid": validation.get("valid"),
        "proposal_fields": validation.get("fields", []),
        "winning_source": repair.get("winning_source"),
        "raw_length": len(result.get("raw", "") or ""),
    })
    record_live_proof(out)
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--max-tokens", type=int, default=160)
    p.add_argument("--temperature", type=float, default=0.2)
    args = p.parse_args()
    doc = run_live_proof(max_tokens=args.max_tokens, temperature=args.temperature)
    print(json.dumps(doc, indent=2))
    return 0 if doc.get("classification", "").startswith("B1044_TRUE_LIVE_DEEPSEEK_PROOF_PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
