"""Static accessibility and responsive-contract checks for the scoped Agora UI."""

from __future__ import annotations

import inspect

from doofus.dashboard import agora_panel
from doofus.dashboard import doofus_dashboard_app


def test_agora_surface_is_scoped_responsive_and_motion_safe() -> None:
    css = agora_panel.AGORA_CSS
    assert ".agora-shell" in css
    assert "@media (max-width: 1023px)" in css
    assert "@media (max-width: 767px)" in css
    assert "@media (prefers-reduced-motion: reduce)" in css
    assert "focus-visible" in css
    assert "min-height: 44px" in css
    assert "transition-duration: 0.01ms" in css


def test_agora_console_exposes_required_operator_surfaces() -> None:
    source = inspect.getsource(agora_panel)
    required_labels = (
        "Mission compiler",
        "Provider constitution",
        "Debate topology",
        "Packet inbox",
        "Evidence matrix",
        "Minority lane",
        "Candidate laboratory",
        "Attribution history",
        "Sanitation preview",
    )
    assert all(label in source for label in required_labels)
    dashboard_source = inspect.getsource(doofus_dashboard_app)
    assert 'ui.tab("Agora")' in dashboard_source
    assert 'ui.tab_panel("Agora")' in dashboard_source
    assert "build_agora_panel()" in dashboard_source
