"""Write missing .md companion files for gen1639 bundle."""
import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "artifacts" / "doofus" / "gen1639-live-verification-v1"


def md(stem: str, payload: dict) -> None:
    lines = [f"# {stem.replace('_', ' ').title()}", ""]
    for k, v in payload.items():
        if isinstance(v, (dict, list)):
            lines.extend([f"## {k}", "", "```json", json.dumps(v, indent=2), "```", ""])
        else:
            lines.append(f"- **{k}**: `{v}`")
    (OUT / f"{stem}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


for stem in [
    "STARTING_STATE",
    "LIVE_GEN1639_LAUNCH_INTENT",
    "live_db_preflight_before_launch",
    "prelaunch_test_results",
    "nonlive_dry_run_guard_probe",
]:
    md(stem, json.loads((OUT / f"{stem}.json").read_text(encoding="utf-8")))

print("done")
