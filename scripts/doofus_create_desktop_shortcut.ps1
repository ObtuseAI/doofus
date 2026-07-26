$ErrorActionPreference = "Stop"
$Root = "C:\sai-auth-doofus"
$Desktop = [Environment]::GetFolderPath("Desktop")
$Launcher = Join-Path $Root "scripts\doofus_launch_dashboard.ps1"
$PythonIcon = Join-Path $Root ".venv_doofus\Scripts\python.exe"
$OldStart = Join-Path $Desktop "Doofus Start.lnk"

if (Test-Path $OldStart) {
    Remove-Item $OldStart -Force
    Write-Host "Removed old shortcut: $OldStart"
}

$path = Join-Path $Desktop "Doofus.lnk"
$oldDash = Join-Path $Desktop "Doofus Live Dashboard.lnk"
if (Test-Path $oldDash) { Remove-Item $oldDash -Force; Write-Host "Removed old shortcut: $oldDash" }
$WshShell = New-Object -ComObject WScript.Shell
$link = $WshShell.CreateShortcut($path)
$link.TargetPath = "powershell.exe"
$link.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$Launcher`""
$link.WorkingDirectory = $Root
$link.Description = "Start Doofus supervisor runtime and live dashboard"
if (Test-Path $PythonIcon) {
    $link.IconLocation = "$PythonIcon,0"
}
$link.Save()
Write-Host "Created: $path"
