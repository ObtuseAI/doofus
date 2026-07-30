"""Localhost-only preview entrypoint for Agora visual acceptance testing."""

from __future__ import annotations

import os

from nicegui import ui

from doofus.dashboard.agora_panel import build_agora_panel


def main() -> None:
    port = int(os.environ["DOOFUS_AGORA_PREVIEW_PORT"])

    @ui.page("/")
    def preview_page() -> None:
        ui.dark_mode().enable()
        ui.query("body").style("margin: 0; background: #070b14;")
        with ui.column().classes("w-full q-pa-md"):
            build_agora_panel()

    ui.run(host="127.0.0.1", port=port, reload=False, show=False)


if __name__ in {"__main__", "__mp_main__"}:
    main()
