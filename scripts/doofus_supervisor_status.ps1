$ErrorActionPreference = "Stop"
Set-Location "C:\sai-auth-doofus"
& ".\.venv_doofus\Scripts\python.exe" -c "from doofus.runtime.runtime_health import supervisor_health; import json; print(json.dumps({'classification':'DOOFUS_SUPERVISOR_STATUS', **supervisor_health()}, indent=2))"
