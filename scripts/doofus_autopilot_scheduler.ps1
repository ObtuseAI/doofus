# Doofus hourly autopilot scheduler — 20 min active, 40 min idle, repeat until stop.
# Stop: python scripts/doofus_hourly_autopilot.py --stop
$Root = Split-Path -Parent $PSScriptRoot
$Py = Join-Path $Root ".venv_doofus\Scripts\python.exe"
if (-not (Test-Path $Py)) { $Py = "python" }
$StopFile = Join-Path $Root "runtime\control\DOOFUS_AUTOPILOT_STOP.request"
$PidFile = Join-Path $Root "runtime\state\autopilot_scheduler.pid"
$HeartbeatFile = Join-Path $Root "runtime\state\autopilot_scheduler_heartbeat.json"
$LogFile = Join-Path $Root "runtime\logs\autopilot_scheduler.log"

function Write-SchedulerLog($msg) {
    $line = "[$(Get-Date -Format o)] $msg"
    Add-Content -Path $LogFile -Value $line -Encoding utf8
    Write-Host $line
}

function Write-Heartbeat($phase) {
    $hb = @{
        at = (Get-Date).ToUniversalTime().ToString("o")
        scheduler_pid = $PID
        phase = $phase
    } | ConvertTo-Json -Compress
    Set-Content -Path $HeartbeatFile -Value $hb -Encoding utf8
}

if (Test-Path $PidFile) {
    $existing = Get-Content $PidFile -ErrorAction SilentlyContinue
    if ($existing -and ($existing -ne $PID)) {
        Stop-Process -Id $existing -Force -ErrorAction SilentlyContinue
    }
}

function Test-AutopilotStopped {
    return Test-Path $StopFile
}

New-Item -ItemType Directory -Force -Path (Split-Path $LogFile) | Out-Null
"$PID" | Out-File -FilePath $PidFile -Encoding ascii -NoNewline
Write-SchedulerLog "started pid=$PID"
Write-SchedulerLog "pattern: 20min active + 40min idle per hour"
Write-SchedulerLog "stop: python scripts/doofus_hourly_autopilot.py --stop"
Write-Heartbeat "running"

while (-not (Test-AutopilotStopped)) {
    Write-SchedulerLog "starting 20-minute session"
    Write-Heartbeat "session_start"
    $exitCode = 0
    try {
        & $Py -u (Join-Path $Root "scripts\doofus_hourly_autopilot.py") --duration-minutes 20 --interval-seconds 90
        $exitCode = $LASTEXITCODE
    } catch {
        Write-SchedulerLog "session error: $_"
        $exitCode = 1
    }
    Write-SchedulerLog "session finished exit=$exitCode"
    Write-Heartbeat "session_end"
    $env:DOOFUS_SKIP_PROCESS_SCAN = "1"
    & $Py -u -m doofus.runtime.session_cleanup
    if ($LASTEXITCODE -ne 0) {
        Write-SchedulerLog "session cleanup exit=$LASTEXITCODE"
    }
    & $Py -u (Join-Path $Root "scripts\doofus_autopilot_followthrough.py")
    Write-Output 'AGENT_LOOP_TICK_DOOFUS_AUTOPILOT {"prompt":"Read runtime/state/autopilot_followthrough.md — summarize last session, confirm scheduler alive, apply safe code fixes if issues listed."}'
    if (Test-AutopilotStopped) { break }
    Write-SchedulerLog "sleeping 40 minutes..."
    $slept = 0
    while ($slept -lt 2400) {
        if (Test-AutopilotStopped) { break }
        Start-Sleep -Seconds 60
        $slept += 60
        Write-Heartbeat "idle"
    }
    if (-not (Test-AutopilotStopped)) {
        & $Py -u (Join-Path $Root "scripts\doofus_autopilot_followthrough.py")
        Write-Output 'AGENT_LOOP_TICK_DOOFUS_AUTOPILOT {"prompt":"Read runtime/state/autopilot_followthrough.md — summarize last session, confirm scheduler alive, apply safe code fixes if issues listed."}'
    }
}

Write-SchedulerLog "stopped"
Write-Heartbeat "stopped"
Remove-Item $PidFile -ErrorAction SilentlyContinue
