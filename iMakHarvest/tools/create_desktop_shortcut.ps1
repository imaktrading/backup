# create_desktop_shortcut.ps1
#
# Create a desktop shortcut (.lnk) for iMakHarvest control_panel.
#
# Usage:
#   PowerShell -ExecutionPolicy Bypass -File tools\create_desktop_shortcut.ps1
#
# Remove:
#   PowerShell -ExecutionPolicy Bypass -File tools\create_desktop_shortcut.ps1 -Action Remove

param (
    [ValidateSet("Create", "Remove")]
    [string]$Action = "Create"
)

$ShortcutName = "iMakHarvest.lnk"
$Desktop = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $Desktop $ShortcutName

if ($Action -eq "Remove") {
    if (Test-Path $ShortcutPath) {
        Remove-Item $ShortcutPath
        Write-Output "[OK] $ShortcutName removed"
    } else {
        Write-Output "[INFO] $ShortcutName not found"
    }
    exit 0
}

# Create
$WorkingDir = "C:\dev\iMak\iMakHarvest"
$Script = Join-Path $WorkingDir "control_panel.py"

# Prefer pythonw.exe (no console window), fallback to python.exe
$PythonW = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
if (-not $PythonW) {
    $PythonW = (Get-Command python.exe -ErrorAction SilentlyContinue).Source
}
if (-not $PythonW) {
    Write-Output "[ERROR] pythonw.exe / python.exe not found in PATH"
    exit 1
}

if (-not (Test-Path $Script)) {
    Write-Output "[ERROR] $Script not found"
    exit 1
}

$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $PythonW
$Shortcut.Arguments = "`"$Script`""
$Shortcut.WorkingDirectory = $WorkingDir
$Shortcut.WindowStyle = 1
$Shortcut.Description = "iMakHarvest GUI control panel (Phase 1a: Mercari URL 抽出)"
$Shortcut.IconLocation = "$PythonW,0"
$Shortcut.Save()

Write-Output "[OK] Shortcut created"
Write-Output "  path:        $ShortcutPath"
Write-Output "  target:      $PythonW"
Write-Output "  arguments:   `"$Script`""
Write-Output "  working dir: $WorkingDir"
Write-Output ""
Write-Output "Remove with: PowerShell -ExecutionPolicy Bypass -File tools\create_desktop_shortcut.ps1 -Action Remove"
