$ErrorActionPreference = "Stop"
Set-Location "C:\sai-auth-doofus"
& ".\scripts\doofus_start_dashboard_persistent.ps1"
Start-Sleep -Seconds 25
& ".\scripts\doofus_dashboard_status.ps1"
