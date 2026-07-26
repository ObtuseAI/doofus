$ErrorActionPreference = "Stop"
$Root = "C:\sai-auth-doofus"
Set-Location $Root
& "$Root\.venv_doofus\Scripts\python.exe" -m doofus.model_router.task_environment_verifier
& "$Root\.venv_doofus\Scripts\python.exe" -m doofus.model_router.desktop_secret_loader
