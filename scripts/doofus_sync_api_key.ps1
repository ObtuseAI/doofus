$ErrorActionPreference = "Stop"
Set-Location "C:\sai-auth-doofus"
.\.venv_doofus\Scripts\python.exe scripts\doofus_attach_api_key.py
.\scripts\doofus_restart_task.ps1
