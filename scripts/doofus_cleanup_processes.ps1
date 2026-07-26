$ErrorActionPreference = "Stop"
Set-Location "C:\sai-auth-doofus"
& ".\.venv_doofus\Scripts\python.exe" -m doofus.runtime.safe_cleanup 2>$null
if ($LASTEXITCODE -ne 0) {
  & ".\.venv_doofus\Scripts\python.exe" -c "from doofus.runtime.safe_cleanup import run_safe_cleanup; import json; print(json.dumps(run_safe_cleanup()))"
}
