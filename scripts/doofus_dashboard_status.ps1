$ErrorActionPreference = "Stop"
Set-Location "C:\sai-auth-doofus"
& ".\.venv_doofus\Scripts\python.exe" -c "from doofus.dashboard.dashboard_health import classify_dashboard_health; from doofus.supervisor.scheduled_task_guard import get_scheduled_task_states; import json; t=get_scheduled_task_states(); h=classify_dashboard_health(t.get('dashboard_state')); print(json.dumps({'classification':'DOOFUS_DASHBOARD_STATUS','health':h,'tasks':t}, indent=2))"
