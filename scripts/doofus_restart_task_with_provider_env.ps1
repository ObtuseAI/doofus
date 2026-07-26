$ErrorActionPreference = "Stop"
$Root = "C:\sai-auth-doofus"
Set-Location $Root
& "$Root\.venv_doofus\Scripts\python.exe" "$Root\scripts\doofus_install_evolution_env.py"
& "$Root\scripts\doofus_restart_runtime_tasks.ps1"
