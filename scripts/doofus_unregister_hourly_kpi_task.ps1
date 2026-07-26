$ErrorActionPreference = "SilentlyContinue"
Unregister-ScheduledTask -TaskName "Doofus-Hourly-KPI-Report" -Confirm:$false
Unregister-ScheduledTask -TaskName "Doofus-2Hour-KPI-Chat-Update" -Confirm:$false
Write-Host "Unregistered KPI scheduled tasks"
