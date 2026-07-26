$ErrorActionPreference = "Stop"
Set-Location "C:\sai-auth-doofus"
& ".\scripts\doofus_start.ps1"
& ".\scripts\doofus_install_evolution_env.py" 2>$null
& ".\.venv_doofus\Scripts\python.exe" "$PWD\scripts\doofus_install_evolution_env.py"
$mgr = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -match 'windows_runtime_manager' }
if (-not $mgr) {
  Start-Process -FilePath ".\.venv_doofus\Scripts\python.exe" -ArgumentList "-m","doofus.runtime.windows_runtime_manager","--serve" -WorkingDirectory (Get-Location) -WindowStyle Hidden
}
Start-Sleep -Seconds 45
& ".\scripts\doofus_runtime_status.ps1"
