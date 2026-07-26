# Hourly KPI report scheduler � runs publish_hourly_kpi_report every 60 minutes.
$ErrorActionPreference = "Stop"
$Root = "C:\sai-auth-doofus"
$Py = Join-Path $Root ".venv_doofus\Scripts\python.exe"
if (-not (Test-Path $Py)) { $Py = "python" }
$LogDir = Join-Path $Root "runtime\logs"
$LogFile = Join-Path $LogDir "hourly_kpi_scheduler.log"
$PidFile = Join-Path $Root "runtime\state\hourly_kpi_scheduler.pid"
$IntervalSeconds = 3600

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Write-Log($msg) {
    $line = "[$(Get-Date -Format o)] $msg"
    Add-Content -Path $LogFile -Value $line -Encoding utf8
}

if (Test-Path $PidFile) {
    $existing = Get-Content $PidFile -ErrorAction SilentlyContinue
    if ($existing -and ($existing -ne $PID)) {
        Stop-Process -Id $existing -Force -ErrorAction SilentlyContinue
    }
}
"$PID" | Out-File -FilePath $PidFile -Encoding ascii -NoNewline
Write-Log "hourly KPI scheduler started pid=$PID interval=${IntervalSeconds}s"

while ($true) {
    try {
        Set-Location $Root
        & $Py (Join-Path $Root "scripts\doofus_hourly_kpi_report.py") 2>&1 | ForEach-Object { Write-Log $_ }
        Write-Log "hourly report published"
    } catch {
        Write-Log "hourly report error: $_"
    }
    Start-Sleep -Seconds $IntervalSeconds
}
