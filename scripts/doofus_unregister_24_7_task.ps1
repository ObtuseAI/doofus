$ErrorActionPreference = "Continue"
foreach ($Name in @("Doofus-24-7-Supervisor", "Doofus-Local-Dashboard")) {
    schtasks /Query /TN $Name 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
        schtasks /Delete /TN $Name /F
        Write-Host "Unregistered: $Name"
    } else {
        Write-Host "Not registered: $Name"
    }
}
