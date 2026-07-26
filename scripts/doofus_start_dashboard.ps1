$ErrorActionPreference = "Stop"
Set-Location "C:\sai-auth-doofus"
$Root = (Get-Location).Path
$Python = Join-Path $Root ".venv_doofus\Scripts\python.exe"
& "$Root\scripts\doofus_cleanup_processes.ps1" -ErrorAction SilentlyContinue
schtasks /Run /TN "Doofus-Local-Dashboard" 2>$null
if ($LASTEXITCODE -ne 0) {
    Start-Process -FilePath $Python -ArgumentList "-m doofus.dashboard.doofus_dashboard_app" -WorkingDirectory $Root -WindowStyle Hidden
}
Start-Sleep -Seconds 3
& "$Root\scripts\doofus_dashboard_status.ps1"
