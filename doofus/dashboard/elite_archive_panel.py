"""Elite archive dashboard panel."""
from __future__ import annotations

from doofus.evolution.elite_archive import get_elite_archive


def get_elite_archive_panel() -> dict:
    return get_elite_archive()
