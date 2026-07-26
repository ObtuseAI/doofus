$ErrorActionPreference = "Stop"
$Root = "C:\sai-auth-doofus"
$Python = "$Root\.venv_doofus\Scripts\python.exe"

Set-Location $Root

& $Python -c "from doofus.safety.on_off_switch import start, clear_emergency; clear_emergency(); start()"

& $Python "$Root\scripts\doofus_kill_start_dashboard.py"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Doofus enabled. Dashboard starting."
Write-Host "Dashboard: http://127.0.0.1:8765"
Write-Host "Run Doofus Live Dashboard shortcut to open the UI."
