"""Validate model proposals locally — no command execution."""
from __future__ import annotations
import json

FORBIDDEN = ("exec", "eval", "subprocess", "os.system", "rm ", "del ")

def validate_proposal(raw: str) -> dict:
    ok = True
    reason = ""
    proposal = None
    low = raw.lower()
    if any(x in low for x in FORBIDDEN):
        return {"valid": False, "reason": "forbidden_content", "proposal": None}
    try:
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0:
            proposal = json.loads(raw[start:end])
    except json.JSONDecodeError:
        ok = False
        reason = "parse_failed"
    return {"valid": ok and proposal is not None, "reason": reason, "proposal": proposal}
