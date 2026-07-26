$ErrorActionPreference = "Stop"
$Root = "C:\sai-auth-doofus"
$Python = "$Root\.venv_doofus\Scripts\python.exe"
$SupervisorTask = "Doofus-24-7-Supervisor"
$DashboardTask = "Doofus-Local-Dashboard"

function Register-DoofusScheduledTask {
    param(
        [string]$Name,
        [string]$Arguments
    )
    Unregister-ScheduledTask -TaskName $Name -Confirm:$false -ErrorAction SilentlyContinue | Out-Null
    $action = New-ScheduledTaskAction -Execute $Python -Argument $Arguments -WorkingDirectory $Root
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero)
    Register-ScheduledTask -TaskName $Name -Action $action -Trigger $trigger -Settings $settings -RunLevel Limited -Force | Out-Null
    Write-Host "Registered: $Name"
}

Set-Location $Root
& "$Root\scripts\doofus_cleanup_processes.ps1"

Register-DoofusScheduledTask -Name $SupervisorTask -Arguments "-m doofus.supervisor.doofus_24_7_supervisor"
Register-DoofusScheduledTask -Name $DashboardTask -Arguments "-m doofus.dashboard.doofus_dashboard_app"

Write-Host ""
Write-Host "NOTE: Tasks run at logon for user $env:USERNAME."
Write-Host "Set OPENROUTER_API_KEY as user-level env var, then log out/in or restart tasks."
Write-Host "Never embed API keys in task actions."
