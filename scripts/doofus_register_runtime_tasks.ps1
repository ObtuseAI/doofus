$ErrorActionPreference = "Stop"
$Root = "C:\sai-auth-doofus"
Set-Location $Root
$Python = Join-Path $Root ".venv_doofus\Scripts\python.exe"
$Interval = New-TimeSpan -Minutes 1

function Register-DoofusTask {
    param([string]$Name, [string]$Arguments)
    Unregister-ScheduledTask -TaskName $Name -Confirm:$false -ErrorAction SilentlyContinue | Out-Null
    $action = New-ScheduledTaskAction -Execute $Python -Argument $Arguments -WorkingDirectory $Root
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero)
    Register-ScheduledTask -TaskName $Name -Action $action -Trigger $trigger -Settings $settings -RunLevel Highest -Force | Out-Null
    Write-Host "Registered: $Name"
}

try {
    Register-DoofusTask -Name "Doofus-Runtime-Manager" -Arguments "-m doofus.runtime.windows_runtime_manager --serve"
    Register-DoofusTask -Name "Doofus-24-7-Supervisor" -Arguments "-m doofus.supervisor.doofus_24_7_supervisor"
    Register-DoofusTask -Name "Doofus-Local-Dashboard" -Arguments "-m doofus.dashboard.doofus_dashboard_app"
    Register-DoofusTask -Name "Doofus-24-7-Watchdog" -Arguments "-m doofus.runtime.windows_runtime_manager --once"
    Register-DoofusTask -Name "Doofus-Dashboard-Watchdog" -Arguments "-m doofus.supervisor.dashboard_watchdog --once"
    & $Python -c "from doofus.supervisor.scheduled_task_guard import record_task_registration; record_task_registration(['Doofus-Runtime-Manager','Doofus-24-7-Supervisor','Doofus-Local-Dashboard','Doofus-24-7-Watchdog','Doofus-Dashboard-Watchdog'])"
    Write-Host '{"classification":"RUNTIME_TASK_REGISTRATION_PASS"}'
    exit 0
} catch {
    Write-Host '{"classification":"RUNTIME_TASK_REGISTRATION_BLOCKED_ELEVATION"}'
    Write-Host "Run: $Root\scripts\doofus_register_runtime_tasks_elevated.ps1"
    exit 2
}
