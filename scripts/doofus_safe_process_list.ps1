$ErrorActionPreference = "Stop"
Set-Location "C:\sai-auth-doofus"
& ".\.venv_doofus\Scripts\python.exe" -c "from doofus.runtime.process_registry import protected_pids; from doofus.runtime.process_classifier import list_doofus_processes; import json; print(json.dumps({'protected': sorted(protected_pids()), 'processes': list_doofus_processes()}, indent=2))"
