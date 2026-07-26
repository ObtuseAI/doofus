# Refresh Shared Folder 12-hour final reports (no secrets).
$ErrorActionPreference = "Stop"
Set-Location "C:\sai-auth-doofus"
$py = ".\.venv_doofus\Scripts\python.exe"
& $py scripts/doofus_12_hour_orchestrator.py --phase b1097 --refresh-only
Write-Host "Finalized Shared Folder reports."
