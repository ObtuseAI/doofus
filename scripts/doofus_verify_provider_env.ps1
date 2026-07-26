$ErrorActionPreference = "Stop"
$Root = "C:\sai-auth-doofus"
Set-Location $Root
& "$Root\scripts\doofus_verify_openrouter_env.ps1"
& "$Root\.venv_doofus\Scripts\python.exe" -m doofus.model_router.provider_router
