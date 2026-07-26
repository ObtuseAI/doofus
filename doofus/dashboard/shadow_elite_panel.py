"""Shadow elite dashboard panel."""
from __future__ import annotations

from doofus.evolution.shadow_elite_archive import get_shadow_elite_archive


def get_shadow_elite_panel() -> dict:
    return get_shadow_elite_archive()
