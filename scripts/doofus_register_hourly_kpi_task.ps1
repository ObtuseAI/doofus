$ErrorActionPreference = "Stop"
$Root = "C:\sai-auth-doofus"
$Python = Join-Path $Root ".venv_doofus\Scripts\python.exe"
if (-not (Test-Path $Python)) { $Python = "python" }
$TaskName = "Doofus-Hourly-KPI-Report"
$Interval = New-TimeSpan -Hours 1

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue | Out-Null

$action = New-ScheduledTaskAction `
    -Execute $Python `
    -Argument (Join-Path $Root "scripts\doofus_hourly_kpi_report.py") `
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

Write-Host "Registered scheduled task: $TaskName (every 1 hour)"
Write-Host "Reports: C:\Users\developer\Desktop\Shared Folder\Doofus-Local-Operation\DOOFUS-HOURLY-KPI-LATEST.md"

# Publish first report immediately
Set-Location $Root
& $Python (Join-Path $Root "scripts\doofus_hourly_kpi_report.py")
