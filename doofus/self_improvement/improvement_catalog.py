"""Doofus-native improvement catalog - load, dedupe, index, write queues."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from doofus.self_improvement.improvement_item import ImprovementItem, ALLOWED_STATUSES, ALLOWED_TYPES
from doofus.self_improvement.improvement_scorer import apply_scores
from doofus.self_improvement.cycle_lesson_extractor import extract_lessons_from_artifacts


def write_pair(out_dir: Path, stem: str, payload: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{stem}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    lines = [f"# {stem.replace('_', ' ').title()}", ""]
    for k, v in payload.items():
        if isinstance(v, (dict, list)):
            lines.extend([f"## {k}", "", "```json", json.dumps(v, indent=2)[:8000], "```", ""])
        else:
            lines.append(f"- **{k}**: `{v}`")
    (out_dir / f"{stem}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


class ImprovementCatalog:
    def __init__(self, items: list[ImprovementItem] | None = None) -> None:
        self.items: list[ImprovementItem] = items or []

    @classmethod
    def from_workspace(cls, workspace: Path, source_generation: int = 1639) -> ImprovementCatalog:
        extracted = extract_lessons_from_artifacts(workspace, source_generation)
        return cls(extracted).dedupe().score_all()

    def add_manual(self, item: ImprovementItem) -> None:
        self.items.append(item)

    def dedupe(self) -> ImprovementCatalog:
        seen: dict[str, ImprovementItem] = {}
        for item in self.items:
            if item.type not in ALLOWED_TYPES:
                continue
            if item.status not in ALLOWED_STATUSES:
                item.status = "candidate"
            existing = seen.get(item.dedupe_key)
            if existing is None or item.score > existing.score:
                seen[item.dedupe_key] = item
        self.items = list(seen.values())
        return self

    def score_all(self) -> ImprovementCatalog:
        apply_scores(self.items)
        self.items.sort(key=lambda x: (-x.score, x.title))
        return self

    def by_type(self, type_: str) -> list[ImprovementItem]:
        return [i for i in self.items if i.type == type_]

    def priority_index(self) -> dict[str, Any]:
        tiers = {"P0": [], "P1": [], "P2": [], "P3": [], "DEFERRED": []}
        for item in self.items:
            if item.score >= 85:
                tier = "P0"
            elif item.score >= 70:
                tier = "P1"
            elif item.score >= 55:
                tier = "P2"
            elif item.status != "deferred":
                tier = "P3"
            else:
                tier = "DEFERRED"
            tiers[tier].append({"id": item.id, "title": item.title, "score": item.score, "type": item.type})
        return {"classification": "DOOFUS_SELF_IMPROVEMENT_PRIORITY_INDEX", "tiers": tiers}

    def subsystem_index(self) -> dict[str, Any]:
        idx: dict[str, list[str]] = {}
        for item in self.items:
            for sub in item.affected_subsystems or ["general"]:
                idx.setdefault(sub, []).append(item.dedupe_key)
        return {"classification": "DOOFUS_SELF_IMPROVEMENT_SUBSYSTEM_INDEX", "subsystems": idx}

    def validation_queue(self) -> dict[str, Any]:
        queued = [
            {
                "id": i.id,
                "title": i.title,
                "type": i.type,
                "score": i.score,
                "validation_method": i.validation_method,
                "required_tests": i.required_tests,
                "status": "queued_for_validation",
            }
            for i in self.items
            if i.score >= 55 and i.status in ("candidate", "queued_for_validation")
        ][:40]
        return {"classification": "DOOFUS_SELF_IMPROVEMENT_VALIDATION_QUEUE", "count": len(queued), "items": queued}

    def to_catalog_dict(self) -> dict[str, Any]:
        by_type: dict[str, int] = {}
        for item in self.items:
            by_type[item.type] = by_type.get(item.type, 0) + 1
        return {
            "classification": "DOOFUS_SELF_IMPROVEMENT_CATALOG",
            "item_count": len(self.items),
            "by_type": by_type,
            "items": [i.to_dict() for i in self.items],
        }

    def write_outputs(self, output_dir: Path) -> dict[str, Any]:
        output_dir.mkdir(parents=True, exist_ok=True)
        write_pair(output_dir, "self_improvement_catalog", self.to_catalog_dict())
        write_pair(output_dir, "priority_index", self.priority_index())
        write_pair(output_dir, "subsystem_index", self.subsystem_index())
        write_pair(output_dir, "validation_queue", self.validation_queue())
        return {
            "item_count": len(self.items),
            "output_dir": str(output_dir),
            "by_type": self.to_catalog_dict()["by_type"],
        }
