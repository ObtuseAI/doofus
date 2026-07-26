$ErrorActionPreference = "Stop"
Set-Location "C:\sai-auth-doofus"
.\.venv_doofus\Scripts\python.exe -c "from doofus.reports.doofus_task_reporter import build_task_report; import json; print(json.dumps(build_task_report(), indent=2))"
