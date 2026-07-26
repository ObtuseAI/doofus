$ErrorActionPreference = "Stop"
$Root = "C:\sai-auth-doofus"
Set-Location $Root
& "$Root\scripts\doofus_cleanup_processes.ps1"
Stop-ScheduledTask -TaskName "Doofus-24-7-Supervisor" -ErrorAction SilentlyContinue
Stop-ScheduledTask -TaskName "Doofus-Local-Dashboard" -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
Start-ScheduledTask -TaskName "Doofus-24-7-Supervisor"
Start-ScheduledTask -TaskName "Doofus-Local-Dashboard"
Start-Sleep -Seconds 8
& "$Root\scripts\doofus_task_status.ps1"
& "$Root\scripts\doofus_verify_openrouter_env.ps1"
