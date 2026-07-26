"""OpenRouter provider healthcheck - dry-run or bounded live smoke."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from doofus.model_router.openrouter_live_config import validate_openrouter_live_config
from doofus.reports.cycle_finalizer import write_artifact_pair


def run_healthcheck(
    *,
    dry_run: bool,
    live_smoke: bool,
    operator_approved: bool,
    max_cost_usd: float,
    output_dir: Path,
) -> dict:
    config = validate_openrouter_live_config(dry_run=dry_run, require_model_id=not dry_run)
    result = {
        "classification": "DOOFUS_OPENROUTER_HEALTHCHECK_DRY_RUN"
        if dry_run
        else "DOOFUS_OPENROUTER_HEALTHCHECK_CONFIG",
        "dry_run": dry_run,
        "live_smoke_requested": live_smoke,
        "live_smoke_executed": False,
        "config": config,
        "max_cost_usd": max_cost_usd,
        "db_mutated": False,
        "checkpoint_mutated": False,
    }

    if live_smoke:
        if not operator_approved:
            result["classification"] = "DOOFUS_OPENROUTER_HEALTHCHECK_REFUSED"
            result["reason"] = "live_smoke requires --operator-approved-provider-smoke"
        elif not config.get("ready"):
            result["classification"] = "DOOFUS_OPENROUTER_HEALTHCHECK_BLOCKED"
            result["reason"] = config.get("blockers")
        else:
            from doofus.model_router.deepseek_v4_flash_adapter import DeepSeekV4FlashAdapter

            import os

            os.environ["DOOFUS_OPERATOR_APPROVED_PROVIDER_SMOKE"] = "1"
            try:
                adapter = DeepSeekV4FlashAdapter.from_env()
                smoke = adapter.propose_mutations(
                    {"prompt": "Reply with JSON: {\"ok\": true}", "max_tokens": 32, "generation": 0}
                )
            finally:
                os.environ.pop("DOOFUS_OPERATOR_APPROVED_PROVIDER_SMOKE", None)
            result["live_smoke_executed"] = True
            result["smoke_classification"] = smoke.get("classification")
            result["smoke_mode"] = smoke.get("mode")
            result["cost_est"] = smoke.get("cost_est")
            result["classification"] = (
                "DOOFUS_OPENROUTER_HEALTHCHECK_LIVE_SMOKE_PASS"
                if smoke.get("classification") == "DOOFUS_MODEL_LIVE"
                else "DOOFUS_OPENROUTER_HEALTHCHECK_LIVE_SMOKE_PARTIAL"
            )

    write_artifact_pair(output_dir, "OPENROUTER_HEALTHCHECK_RESULT", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--live-smoke", action="store_true")
    parser.add_argument("--operator-approved-provider-smoke", action="store_true")
    parser.add_argument("--max-cost-usd", type=float, default=0.01)
    args = parser.parse_args()
    out = Path(args.output_dir)
    dry = args.dry_run or not args.live_smoke
    payload = run_healthcheck(
        dry_run=dry,
        live_smoke=args.live_smoke,
        operator_approved=args.operator_approved_provider_smoke,
        max_cost_usd=args.max_cost_usd,
        output_dir=out,
    )
    print(json.dumps({"classification": payload["classification"], "ready": payload["config"].get("ready")}, indent=2))
    return 0 if "PASS" in payload["classification"] or payload["classification"].endswith("DRY_RUN") or payload["classification"].endswith("CONFIG") else 1


if __name__ == "__main__":
    raise SystemExit(main())
