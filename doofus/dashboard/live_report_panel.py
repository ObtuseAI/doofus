from doofus.dashboard.live_data_api import get_latest_report_paths
from doofus.core.doofus_paths import SHARED

def build_report_panel() -> dict:
    return {"shared_folder": str(SHARED), "reports": get_latest_report_paths()}
