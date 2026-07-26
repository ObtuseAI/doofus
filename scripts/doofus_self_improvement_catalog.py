"""Build Doofus self-improvement catalog from gen1637-gen1639 artifacts."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE))

from doofus.self_improvement.improvement_catalog import ImprovementCatalog
from doofus.self_improvement.next_cycle_seed_builder import build_seed_recommendations


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Doofus self-improvement catalog.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--source-generation", type=int, default=1639)
    args = parser.parse_args()

    catalog = ImprovementCatalog.from_workspace(WORKSPACE, args.source_generation)
    result = catalog.write_outputs(args.output_dir)
    seeds = build_seed_recommendations(catalog, args.output_dir)
    result["seed_count"] = seeds.get("seed_count")
    print(json.dumps(result, indent=2))
    return 0 if result["item_count"] >= 50 else 1


if __name__ == "__main__":
    raise SystemExit(main())
