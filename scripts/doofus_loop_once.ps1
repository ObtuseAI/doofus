$ErrorActionPreference = "Stop"
Set-Location "C:\sai-auth-doofus"
.\.venv_doofus\Scripts\python.exe -m doofus.supervisor.doofus_loop_runner --once --dry-run
