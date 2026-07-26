"""Verify scheduled-task processes can see OpenRouter key — REDACTED output only."""
from __future__ import annotations

import json
import os

from doofus.core.doofus_env_loader import load_doofus_env
from doofus.model_router.auth_source_resolver import resolve_auth_source
from doofus.model_router.secret_source_validator import validate_secret_value
from doofus.safety.secret_guard import assert_no_secret_in_payload


def verify_task_environment() -> dict:
    load_doofus_env()
    proc = os.environ.get("OPENROUTER_API_KEY", "").strip()
    resolved = resolve_auth_source(include_desktop=True)
    proc_meta = validate_secret_value(proc)
    return assert_no_secret_in_payload({
        "classification": "DOOFUS_TASK_ENV_VERIFIER_READY",
        "process_key_present": bool(proc),
        "process_length_bucket": proc_meta["secret_length_bucket"],
        "process_key_shape": proc_meta["key_shape"],
        "resolved_source_name": resolved.get("source_name", "missing"),
        "resolved_length_bucket": resolved.get("secret_length_bucket", "unknown"),
        "resolved_key_shape": resolved.get("key_shape", "unknown"),
        "secret_value": "REDACTED",
    })


def main() -> int:
    print(json.dumps(verify_task_environment(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
