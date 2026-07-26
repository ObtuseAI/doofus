$ErrorActionPreference = "Stop"
$Root = "C:\sai-auth-doofus"
Set-Location $Root
& "$Root\.venv_doofus\Scripts\python.exe" "$Root\scripts\doofus_install_provider_env.py"
