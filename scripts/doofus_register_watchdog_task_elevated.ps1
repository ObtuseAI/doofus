# Run as Administrator — registers Doofus watchdog scheduled tasks (no secrets).
$ErrorActionPreference = "Stop"
$Root = "C:\sai-auth-doofus"
Set-Location $Root
& "$Root\scripts\doofus_register_watchdog_task.ps1"
exit $LASTEXITCODE
