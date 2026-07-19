[CmdletBinding()]
param(
    [string]$ShortcutPath = (Join-Path $PSScriptRoot "FlatCAM.lnk")
)

$repoRoot = $PSScriptRoot
$pythonw = Join-Path $repoRoot ".venv\Scripts\pythonw.exe"
$entryPoint = Join-Path $repoRoot "flatcam.py"
$icon = Join-Path $repoRoot "assets\resources\flatcam_icon256.ico"

foreach ($requiredFile in @($pythonw, $entryPoint, $icon)) {
    if (-not (Test-Path -LiteralPath $requiredFile -PathType Leaf)) {
        throw "Required launcher file was not found: $requiredFile"
    }
}

$shortcutParent = Split-Path -Parent $ShortcutPath
if ($shortcutParent -and -not (Test-Path -LiteralPath $shortcutParent)) {
    New-Item -ItemType Directory -Path $shortcutParent -Force | Out-Null
}

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($ShortcutPath)
$shortcut.TargetPath = $pythonw
$shortcut.Arguments = '"' + $entryPoint + '"'
$shortcut.WorkingDirectory = $repoRoot
$shortcut.IconLocation = "$icon,0"
$shortcut.Description = "Launch FlatCAM from $repoRoot"
$shortcut.WindowStyle = 1
$shortcut.Save()

Write-Host "Created shortcut: $ShortcutPath" -ForegroundColor Green
Write-Host "Right-click it and choose 'Pin to taskbar'." -ForegroundColor White
