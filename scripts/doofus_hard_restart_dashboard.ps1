$ErrorActionPreference = "Stop"
$Root = "C:\sai-auth-doofus"
$Python = "$Root\.venv_doofus\Scripts\python.exe"
Set-Location $Root

# Kill anything on 8765
Get-NetTCPConnection -LocalPort 8765 -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }

# Kill duplicate runtime managers (keep newest)
$mgrs = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match 'windows_runtime_manager' } |
    Sort-Object ProcessId -Descending
if ($mgrs.Count -gt 1) {
    $mgrs | Select-Object -Skip 1 | ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
}

# Kill duplicate dashboard modules
Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match 'doofus\.dashboard\.doofus_dashboard_app' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

Start-Sleep -Seconds 2

& $Python -c "from doofus.supervisor.process_singleton import cleanup_stale_lock; cleanup_stale_lock('doofus_dashboard')"
& $Python -c "from doofus.runtime.runtime_repair import ensure_dashboard; import json; print(json.dumps(ensure_dashboard(force=True), indent=2))"

$deadline = (Get-Date).AddSeconds(60)
while ((Get-Date) -lt $deadline) {
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:8765" -UseBasicParsing -TimeoutSec 5
        if ($r.StatusCode -eq 200) {
            Write-Host "OK: Dashboard HTTP 200"
            exit 0
        }
    } catch {
        Start-Sleep -Seconds 2
    }
}
Write-Host "FAIL: Dashboard not reachable"
exit 1
