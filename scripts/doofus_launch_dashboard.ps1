$ErrorActionPreference = "Stop"
$Root = "C:\sai-auth-doofus"
$Python = "$Root\.venv_doofus\Scripts\python.exe"
Set-Location $Root
& $Python "$Root\scripts\doofus_launch_dashboard.py"
exit $LASTEXITCODE
