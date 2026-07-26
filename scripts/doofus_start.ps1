$ErrorActionPreference = "Stop"
Set-Location "C:\sai-auth-doofus"
.\.venv_doofus\Scripts\python.exe -c "from doofus.safety.on_off_switch import start; print(start())"
