$ErrorActionPreference = "Stop"
Set-Location "C:\sai-auth-doofus"
& ".\.venv_doofus\Scripts\python.exe" -c "from doofus.runtime.runtime_repair import ensure_dashboard; import json; print(json.dumps(ensure_dashboard()))"
