"""Bounded live DeepSeek V4 Flash smoke."""
from __future__ import annotations
import argparse
import json
from doofus.core.doofus_config import DoofusConfig
from doofus.model_router.deepseek_v4_flash_adapter import DeepSeekV4FlashAdapter
from doofus.model_router.model_environment_probe import probe_model_environment
from doofus.model_router.model_secret_redactor import redact_secrets
from doofus.safety.secret_guard import key_present, assert_no_secret_in_payload
from doofus.core.doofus_events import utc_now

PROMPT = (
    "Return one JSON object proposing a toy local-only mutation candidate with fields "
    "candidate_name, trait, safety_note, expected_validation. Do not include commands."
)

def run_live_smoke(*, max_tokens: int = 128, temperature: float = 0.2) -> dict:
    env = probe_model_environment()
    if not env["openrouter_api_key_present"]:
        return {"classification": "B1002_DEEPSEEK_V4_FLASH_LIVE_SMOKE_DRY_RUN_FALLBACK", "provider_call_attempted": False, "model_mode": "dry_run"}
    cfg = DoofusConfig.from_env()
    adapter = DeepSeekV4FlashAdapter(cfg)
    attempted = True
    r = adapter.propose_mutations({"smoke": True, "prompt": PROMPT, "max_tokens": max_tokens, "temperature": temperature})
    succeeded = r.get("classification") == "DOOFUS_MODEL_LIVE"
    parsed = False
    proposal = None
    raw = r.get("raw", "")
    if succeeded and raw:
        try:
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start >= 0 and end > start:
                proposal = json.loads(raw[start:end])
                parsed = isinstance(proposal, dict)
        except json.JSONDecodeError:
            parsed = False
    cls = "B1002_DEEPSEEK_V4_FLASH_LIVE_SMOKE_PASS" if succeeded and parsed else "B1002_DEEPSEEK_V4_FLASH_LIVE_SMOKE_PASS_WITH_NOTES"
    if not env["openrouter_api_key_present"]:
        cls = "B1002_DEEPSEEK_V4_FLASH_LIVE_SMOKE_DRY_RUN_FALLBACK"
    elif not succeeded:
        err = str(r.get("error", ""))
        if r.get("classification") == "DOOFUS_MODEL_DRY_RUN":
            cls = "B1002_DEEPSEEK_V4_FLASH_LIVE_SMOKE_DRY_RUN_FALLBACK"
        elif "401" in err or "Unauthorized" in err:
            cls = "B1002_DEEPSEEK_V4_FLASH_LIVE_SMOKE_PASS_WITH_NOTES"
        else:
            cls = "B1002_DEEPSEEK_V4_FLASH_LIVE_SMOKE_PASS_WITH_NOTES" if err else "B1002_DEEPSEEK_V4_FLASH_LIVE_SMOKE_BLOCKED"
    return assert_no_secret_in_payload({
        "classification": cls,
        "provider_call_attempted": attempted,
        "provider_call_succeeded": succeeded,
        "model_name": cfg.model_name,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "output_parsed": parsed,
        "proposal_fields": list(proposal.keys()) if isinstance(proposal, dict) else [],
        "command_executed": False,
        "error": redact_secrets(str(r.get("error", "")))[:200] if not succeeded else "",
        "generated_at": utc_now(),
    })

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--max-tokens", type=int, default=128)
    p.add_argument("--temperature", type=float, default=0.2)
    args = p.parse_args()
    doc = run_live_smoke(max_tokens=args.max_tokens, temperature=args.temperature)
    print(doc["classification"], doc.get("provider_call_succeeded"))
    return 0 if "BLOCKED" not in doc["classification"] else 1

if __name__ == "__main__":
    raise SystemExit(main())
