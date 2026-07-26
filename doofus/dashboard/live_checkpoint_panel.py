from doofus.dashboard.live_data_api import get_checkpoint_status, get_heartbeat_status

def build_checkpoint_panel() -> dict:
    return {"checkpoint": get_checkpoint_status(), "heartbeat": get_heartbeat_status()}
