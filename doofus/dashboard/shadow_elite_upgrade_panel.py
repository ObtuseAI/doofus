"""Shadow elite upgrade dashboard panel."""
from __future__ import annotations

from doofus.evolution.shadow_elite_upgrade_queue import queue_summary
from doofus.evolution.shadow_elite_archive import get_shadow_elite_archive


def get_shadow_elite_upgrade_panel() -> dict:
    q = queue_summary()
    se = get_shadow_elite_archive()
    return {
        "shadow_elite_count": se.get("shadow_elite_count", 0),
        "upgraded_count": se.get("upgraded_count", 0),
        "upgrade_queue": q,
        "upgrades": q.get("upgrades", 0),
        "retirements": q.get("retirements", 0),
    }
