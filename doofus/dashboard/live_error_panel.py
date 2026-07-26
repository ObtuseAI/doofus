from doofus.dashboard.live_state_reader import read_latest_error

def build_error_panel() -> dict:
    return {"last_error": read_latest_error() or "none"}
