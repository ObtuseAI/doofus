param(
    [ValidateSet("supervisor", "dashboard", "both")]
    [string]$Target = "both"
)
$ErrorActionPreference = "Stop"
$Root = "C:\sai-auth-doofus"
Set-Location $Root
& "$Root\scripts\doofus_cleanup_processes.ps1"

function Restart-DoofusTask($Name) {
    schtasks /Query /TN $Name 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Task not registered: $Name"
        return
    }
    schtasks /End /TN $Name 2>$null | Out-Null
    Start-Sleep -Seconds 2
    Start-ScheduledTask -TaskName $Name
    Write-Host "Restarted: $Name"
}

if ($Target -eq "supervisor" -or $Target -eq "both") {
    Restart-DoofusTask "Doofus-24-7-Supervisor"
}
if ($Target -eq "dashboard" -or $Target -eq "both") {
    Restart-DoofusTask "Doofus-Local-Dashboard"
}

Set-Location "C:\sai-auth-doofus"
.\scripts\doofus_task_status.ps1
