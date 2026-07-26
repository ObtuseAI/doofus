$ErrorActionPreference = "Stop"
Set-Location "C:\sai-auth-doofus"
$py = ".\.venv_doofus\Scripts\python.exe"
& $py -c "from doofus.safety.on_off_switch import status; from doofus.dashboard.dashboard_data import summary; from doofus.config.proof_builder_runtime_config import runtime_snapshot as pr; from doofus.config.evolution_runtime_config import runtime_snapshot as er; import json; print(json.dumps({'switch': status(), 'summary': summary(), 'proof_builder_runtime': pr(), 'evolution_runtime': er()}, indent=2))"
