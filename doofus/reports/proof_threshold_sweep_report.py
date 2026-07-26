"""Proof threshold sweep report CLI."""
from __future__ import annotations

import json
import os

from doofus.core.doofus_paths import PROOF_BUILDER_TUNING_DIR
from doofus.scoring.proof_threshold_sweep import sweep


def main() -> None:
    PROOF_BUILDER_TUNING_DIR.mkdir(parents=True, exist_ok=True)
    result = sweep()
    cls = "B1104_THRESHOLD_SWEEP_TUNING_NO_ADJUSTMENT"
    if result.get("recommended_threshold") is not None:
        cls = "B1104_THRESHOLD_SWEEP_TUNING_ADJUSTMENT_APPLIED"
        os.environ["DOOFUS_MIN_PROOF_DENSITY_SCORE"] = str(result["recommended_threshold"])
        (PROOF_BUILDER_TUNING_DIR / "threshold_applied.json").write_text(
            json.dumps({"threshold": result["recommended_threshold"]}, indent=2), encoding="utf-8"
        )
    elif result.get("recommendation") == "keep_threshold_fix_generator":
        cls = "B1104_THRESHOLD_SWEEP_TUNING_PASS_WITH_NOTES"
    out = {"classification": cls, **result}
    (PROOF_BUILDER_TUNING_DIR / "b1104_threshold_sweep_tuning.json").write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    (PROOF_BUILDER_TUNING_DIR / "B1104_THRESHOLD_SWEEP_TUNING.md").write_text(
        f"# B1104 Threshold Sweep\n\nRecommendation: {result.get('recommendation')}\n", encoding="utf-8"
    )
    print(json.dumps({"classification": cls, "recommended": result.get("recommended_threshold")}, indent=2))


if __name__ == "__main__":
    main()
