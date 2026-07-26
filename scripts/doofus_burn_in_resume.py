"""Resume interrupted burn-in for remaining seconds."""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone

from doofus.core.doofus_paths import BURN_IN_AUDIT_DIR
from doofus.reports.burn_in_metrics_snapshot import capture_metrics_snapshot

BURN_PATH = BURN_IN_AUDIT_DIR / "b1071_2_5_hour_live_burn_in.json"
TARGET = 9000
INTERVAL = 900


def main() -> None:
    data = json.loads(BURN_PATH.read_text(encoding="utf-8"))
    done = max((c.get("elapsed_seconds", 0) for c in data.get("checkpoints", [])), default=0)
    remaining = max(0, TARGET - done)
    print(json.dumps({"done_seconds": done, "remaining_seconds": remaining}, indent=2))
    if remaining <= 0:
        data["status"] = "complete"
        data["burn_in_end"] = datetime.now(timezone.utc).isoformat()
        BURN_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return

    elapsed_base = done
    waited = 0
    while waited < remaining:
        sleep_for = min(INTERVAL, remaining - waited)
        time.sleep(sleep_for)
        waited += sleep_for
        total_elapsed = elapsed_base + waited
        cp = capture_metrics_snapshot(label=f"checkpoint_{total_elapsed}")
        data["checkpoints"].append({"elapsed_seconds": total_elapsed, "snapshot": cp})
        data["rate_limit_events"] = cp.get("rate_limit_events_total", 0)
        data["cooldown_events"] = cp.get("cooldown_events_total", 0)
        if cp.get("provider_auth_status") == "rate_limited":
            data["classification"] = "B1071_2_5_HOUR_LIVE_BURN_IN_RATE_LIMITED_WITH_NOTES"
        BURN_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")

    data["status"] = "complete"
    data["burn_in_end"] = datetime.now(timezone.utc).isoformat()
    if data.get("classification") == "B1071_2_5_HOUR_LIVE_BURN_IN_PASS" and data.get("rate_limit_events", 0) > 0:
        data["classification"] = "B1071_2_5_HOUR_LIVE_BURN_IN_RATE_LIMITED_WITH_NOTES"
    BURN_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    md = BURN_IN_AUDIT_DIR / "B1071_2_5_HOUR_LIVE_BURN_IN.md"
    md.write_text(
        f"# B1071 2.5-Hour Live Burn-In\n\n"
        f"Classification: `{data['classification']}`\n\n"
        f"Start: {data.get('burn_in_start')}\nEnd: {data.get('burn_in_end')}\n"
        f"Checkpoints: {len(data.get('checkpoints', []))}\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": "complete", "classification": data["classification"]}, indent=2))


if __name__ == "__main__":
    main()
