$ErrorActionPreference = "Stop"
Set-Location "C:\sai-auth-doofus"
if (!(Test-Path ".\.venv_doofus\Scripts\python.exe")) {
  py -3 -m venv .venv_doofus
}
.\.venv_doofus\Scripts\python.exe -m pip install --upgrade pip setuptools wheel
.\.venv_doofus\Scripts\python.exe -m pip install -e ".[dev]"
Write-Host "Doofus venv ready"
