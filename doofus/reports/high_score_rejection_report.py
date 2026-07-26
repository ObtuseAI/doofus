"""High-score rejection miner report CLI."""
from __future__ import annotations

import json

from doofus.core.doofus_paths import PROOF_BUILDER_TUNING_DIR
from doofus.proof.high_score_rejection_miner import mine_high_score_rejections


def main() -> None:
    PROOF_BUILDER_TUNING_DIR.mkdir(parents=True, exist_ok=True)
    result = mine_high_score_rejections()
    cls = "B1101_HIGH_SCORE_REJECTION_MINER_PASS_WITH_NOTES" if result["count_score_gte_threshold"] > 0 else "B1101_HIGH_SCORE_REJECTION_MINER_PASS"
    out = {"classification": cls, **result}
    (PROOF_BUILDER_TUNING_DIR / "b1101_high_score_rejection_miner.json").write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    (PROOF_BUILDER_TUNING_DIR / "B1101_HIGH_SCORE_REJECTION_MINER.md").write_text(
        f"# B1101 High-Score Rejection Miner\n\nCount >= 0.72: {result['count_score_gte_threshold']}\n", encoding="utf-8"
    )
    print(json.dumps({"classification": cls, "count": result["count_score_gte_threshold"]}, indent=2))


if __name__ == "__main__":
    main()
