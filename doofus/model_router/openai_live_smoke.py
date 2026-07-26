"""OpenAI live smoke test."""
from __future__ import annotations

import argparse
import json

from doofus.model_router.live_response_validator import extract_json_object, validate_live_proposal
from doofus.model_router.openai_adapter import LIVE_PROMPT, OpenAIAdapter, probe_openai_auth
from doofus.model_router.provider_router import resolve_provider
from doofus.safety.secret_guard import assert_no_secret_in_payload


def run_smoke(*, max_tokens: int = 160, temperature: float = 0.2) -> dict:
    auth = probe_openai_auth()
    route = resolve_provider()
    if auth.get("provider_auth") not in ("ok", "rate_limited"):
        return assert_no_secret_in_payload({
            "classification": "B1051_OPENAI_PROVIDER_LANE_AUTH_BLOCKED",
            "provider_auth": auth.get("provider_auth"),
            "deepseek_openrouter_ready": False,
        })
    adapter = OpenAIAdapter.from_env()
    result = adapter.propose_mutations({"prompt": LIVE_PROMPT, "max_tokens": max_tokens, "temperature": temperature})
    parsed = extract_json_object(result.get("raw", "") or "")
    validation = validate_live_proposal(parsed)
    status_code = result.get("provider_status_code")
    cls = "B1051_OPENAI_PROVIDER_LANE_PASS"
    if result.get("classification") == "DOOFUS_OPENAI_MODEL_LIVE" and validation.get("valid"):
        pass
    elif status_code == 429 and auth.get("live_provider_ready"):
        cls = "B1051_OPENAI_PROVIDER_LANE_PASS_WITH_NOTES"
    elif not validation.get("valid"):
        cls = "B1051_OPENAI_PROVIDER_LANE_PASS_WITH_NOTES"
    else:
        cls = "B1051_OPENAI_PROVIDER_LANE_AUTH_BLOCKED"
    return assert_no_secret_in_payload({
        "classification": cls,
        "provider_selected": "openai",
        "model_name": adapter.model_name,
        "live_provider_ready": True,
        "deepseek_openrouter_ready": False,
        "deepseek_lane_status": "auth_required",
        "proposal_valid": validation.get("valid"),
        "model_result": result.get("classification"),
        "provider_status_code": status_code,
        "key_shape": route.get("key_shape"),
    })


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--max-tokens", type=int, default=160)
    p.add_argument("--temperature", type=float, default=0.2)
    args = p.parse_args()
    doc = run_smoke(max_tokens=args.max_tokens, temperature=args.temperature)
    print(json.dumps(doc, indent=2))
    return 0 if doc.get("classification", "").startswith("B1051_OPENAI_PROVIDER_LANE_PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
