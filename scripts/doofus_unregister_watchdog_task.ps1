$ErrorActionPreference = "Stop"
foreach ($Name in @("Doofus-24-7-Watchdog", "Doofus-Dashboard-Watchdog")) {
    Unregister-ScheduledTask -TaskName $Name -Confirm:$false -ErrorAction SilentlyContinue | Out-Null
    Write-Host "Unregistered: $Name"
}
