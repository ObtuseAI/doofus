"""Minimal NiceGUI smoke test."""
from nicegui import ui

ui.label("DOOFUS DASHBOARD SMOKE TEST — if you see this, NiceGUI works").classes("text-h4 text-white")
ui.label("Status: RUNNING | Cand: 4612 | Port check OK").classes("text-lg text-green")

ui.run(host="127.0.0.1", port=8767, reload=False, show=False)
