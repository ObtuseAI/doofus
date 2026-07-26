$ErrorActionPreference = "Stop"
Set-Location "C:\sai-auth-doofus"
$Root = (Get-Location).Path
$Python = Join-Path $Root ".venv_doofus\Scripts\python.exe"
$Interval = New-TimeSpan -Minutes 1

function Register-WatchdogTask {
    param([string]$Name, [string]$ModuleArgs)
    Unregister-ScheduledTask -TaskName $Name -Confirm:$false -ErrorAction SilentlyContinue | Out-Null
    $action = New-ScheduledTaskAction -Execute $Python -Argument $ModuleArgs -WorkingDirectory $Root
    $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval $Interval -RepetitionDuration ([TimeSpan]::MaxValue)
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
    Register-ScheduledTask -TaskName $Name -Action $action -Trigger $trigger -Settings $settings -RunLevel Highest -Force | Out-Null
    Write-Host "Registered: $Name"
}

try {
    Register-WatchdogTask -Name "Doofus-24-7-Watchdog" -ModuleArgs "-m doofus.supervisor.supervisor_watchdog --once"
    Register-WatchdogTask -Name "Doofus-Dashboard-Watchdog" -ModuleArgs "-m doofus.supervisor.dashboard_watchdog --once"
    Write-Host '{"classification":"WATCHDOG_REGISTRATION_PASS","tasks":["Doofus-24-7-Watchdog","Doofus-Dashboard-Watchdog"]}'
    exit 0
} catch {
    Write-Host '{"classification":"WATCHDOG_REGISTRATION_BLOCKED_ELEVATION","error":"elevation required"}'
    Write-Host "Run elevated helper: $Root\scripts\doofus_register_watchdog_task_elevated.ps1"
    exit 2
}
