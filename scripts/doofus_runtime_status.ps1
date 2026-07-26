$ErrorActionPreference = "Stop"
Set-Location "C:\sai-auth-doofus"
& ".\.venv_doofus\Scripts\python.exe" -c "from doofus.runtime.runtime_health import get_runtime_health; import json; print(json.dumps(get_runtime_health(), indent=2, default=str))"
