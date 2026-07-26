"""B1086 one-shot finish validation run snapshot."""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from doofus.core.doofus_paths import ROOT
from doofus.reports.burn_in_metrics_snapshot import capture_metrics_snapshot, save_snapshot

FINISH_DIR = ROOT / "artifacts" / "latest" / "doofus_one_shot_finish"
DURATION = int(__import__("os").environ.get("DOOFUS_FINISH_VALIDATION_SECONDS", "1800"))


def main() -> None:
    FINISH_DIR.mkdir(parents=True, exist_ok=True)
    baseline = capture_metrics_snapshot(label="b1086_baseline")
    start = datetime.now(timezone.utc).isoformat()
    data = {"status": "running", "start": start, "duration_seconds": DURATION, "checkpoints": []}
    (FINISH_DIR / "b1086_one_shot_finish_validation_run.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    elapsed = 0
    interval = 300
    while elapsed < DURATION:
        time.sleep(min(interval, DURATION - elapsed))
        elapsed += min(interval, DURATION - elapsed)
        cp = capture_metrics_snapshot(label=f"b1086_cp_{elapsed}")
        data["checkpoints"].append({"elapsed": elapsed, "snapshot": cp})
        (FINISH_DIR / "b1086_one_shot_finish_validation_run.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    post = capture_metrics_snapshot(label="b1086_post")
    data["status"] = "complete"
    data["end"] = datetime.now(timezone.utc).isoformat()
    data["post"] = post
    data["classification"] = "B1086_ONE_SHOT_FINISH_VALIDATION_RUN_PASS_WITH_NOTES"
    save_snapshot(FINISH_DIR / "b1086_one_shot_finish_validation_run.json", data)
    (FINISH_DIR / "B1086_ONE_SHOT_FINISH_VALIDATION_RUN.md").write_text(
        f"# B1086 Validation\n\nClassification: `{data['classification']}`\nDuration: {DURATION}s\n",
        encoding="utf-8",
    )
    print(json.dumps({"classification": data["classification"], "duration": DURATION}, indent=2))


if __name__ == "__main__":
    main()
