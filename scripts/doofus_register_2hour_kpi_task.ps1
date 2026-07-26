$ErrorActionPreference = "Stop"
$Root = "C:\sai-auth-doofus"
$Python = Join-Path $Root ".venv_doofus\Scripts\python.exe"
if (-not (Test-Path $Python)) { $Python = "python" }
$OldTask = "Doofus-Hourly-KPI-Report"
$TaskName = "Doofus-2Hour-KPI-Chat-Update"
$Interval = New-TimeSpan -Hours 2

Unregister-ScheduledTask -TaskName $OldTask -Confirm:$false -ErrorAction SilentlyContinue | Out-Null
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue | Out-Null

$action = New-ScheduledTaskAction `
    -Execute $Python `
    -Argument (Join-Path $Root "scripts\doofus_kpi_chat_update.py") `
    -WorkingDirectory $Root

$trigger = New-ScheduledTaskTrigger `
    -Once `
    -At (Get-Date) `
    -RepetitionInterval $Interval `
    -RepetitionDuration (New-TimeSpan -Days 3650)

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -RunLevel Limited `
    -Force | Out-Null

Write-Host "Registered: $TaskName (every 2 hours, chat-only KPI refresh)"
Write-Host "State file: $Root\runtime\state\kpi_chat_update.md"

Set-Location $Root
& $Python (Join-Path $Root "scripts\doofus_kpi_chat_update.py")
