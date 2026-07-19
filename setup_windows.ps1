# FlatCAM Windows Setup Script
# Creates a virtual environment and installs all dependencies.
#
# Usage (from repo root, in PowerShell):
#   Set-ExecutionPolicy -Scope CurrentUser RemoteSigned   # if needed, once
#   .\setup_windows.ps1
#   .\setup_windows.ps1 -PythonExe "C:\Python312\python.exe"
#
# Requires Python 3.11 or 3.12.  Python 3.14 may lack binary wheels for
# VisPy / PyOpenGL / GDAL.

param(
    [string]$PythonExe = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

# ---------------------------------------------------------------------------
# 1. Locate a suitable Python
# ---------------------------------------------------------------------------

function Find-Python {
    if ($PythonExe -ne "" -and (Test-Path $PythonExe)) { return $PythonExe }

    foreach ($ver in @("3.12", "3.11", "3.13", "3.10")) {
        try {
            $exe = (& py "-$ver" -c "import sys; print(sys.executable)" 2>$null)
            if ($LASTEXITCODE -eq 0 -and $exe) { return $exe.Trim() }
        } catch {}
    }
    foreach ($cmd in @("python3", "python")) {
        try {
            $exe = (& $cmd -c "import sys; print(sys.executable)" 2>$null)
            if ($LASTEXITCODE -eq 0 -and $exe) { return $exe.Trim() }
        } catch {}
    }
    throw "No suitable Python found. Install Python 3.11 or 3.12 from python.org."
}

$python = Find-Python
$pyVer  = (& $python --version 2>&1)

Write-Host ""
Write-Host "=== FlatCAM Windows Setup ===" -ForegroundColor Cyan
Write-Host "Using: $python  ($pyVer)"

if ($pyVer -match "3\.1[4-9]") {
    Write-Host ""
    Write-Host "WARNING: Python 3.14+ detected. Some wheels (VisPy, PyOpenGL, GDAL) may not exist for 3.14." -ForegroundColor Yellow
    Write-Host "Prefer Python 3.12 if install fails:" -ForegroundColor Yellow
    Write-Host '  .\setup_windows.ps1 -PythonExe "C:\path\to\python3.12.exe"' -ForegroundColor Yellow
}

# ---------------------------------------------------------------------------
# 2. Create virtual environment
# ---------------------------------------------------------------------------

$venvPath = Join-Path $repoRoot ".venv"
$vPy      = Join-Path $venvPath "Scripts\python.exe"

if (Test-Path $venvPath) {
    Write-Host ""
    Write-Host ".venv already exists -- skipping creation. Delete .venv manually to start fresh." -ForegroundColor Yellow
} else {
    Write-Host ""
    Write-Host "Creating virtual environment at .venv ..." -ForegroundColor Cyan
    & $python -m venv $venvPath
    if ($LASTEXITCODE -ne 0) { throw "Failed to create virtual environment." }
}

# ---------------------------------------------------------------------------
# 3. Upgrade pip / wheel / setuptools inside the venv
# ---------------------------------------------------------------------------

Write-Host ""
Write-Host "Upgrading pip, wheel, setuptools ..." -ForegroundColor Cyan
& $vPy -m pip install --upgrade pip wheel setuptools
if ($LASTEXITCODE -ne 0) { throw "Failed to upgrade pip." }

# ---------------------------------------------------------------------------
# 4. Install all requirements
# ---------------------------------------------------------------------------

$reqFile = Join-Path $repoRoot "requirements.txt"

Write-Host ""
Write-Host "Installing dependencies (this may take several minutes) ..." -ForegroundColor Cyan
& $vPy -m pip install -r $reqFile
$coreOk = ($LASTEXITCODE -eq 0)

if (-not $coreOk) {
    Write-Host ""
    Write-Host "ERROR: Dependency install failed. See output above." -ForegroundColor Red
    exit 1
}

$requirementsHash = (Get-FileHash -Algorithm SHA256 $reqFile).Hash.ToLowerInvariant()
$requirementsMarker = Join-Path $venvPath ".flatcam-requirements.sha256"
[System.IO.File]::WriteAllText($requirementsMarker, $requirementsHash, [System.Text.Encoding]::ASCII)

# ---------------------------------------------------------------------------
# 5. Quick sanity check
# ---------------------------------------------------------------------------

Write-Host ""
Write-Host "Verifying key imports ..." -ForegroundColor Cyan

$checks = @(
    @{ name = "PyQt6";      imp = "import PyQt6.QtCore" },
    @{ name = "vispy";      imp = "import vispy" },
    @{ name = "shapely";    imp = "import shapely" },
    @{ name = "numpy";      imp = "import numpy" },
    @{ name = "simplejson"; imp = "import simplejson" },
    @{ name = "ezdxf";      imp = "import ezdxf" },
    @{ name = "matplotlib"; imp = "import matplotlib" },
    @{ name = "rtree";      imp = "import rtree" },
    @{ name = "rasterio";   imp = "import rasterio; assert rasterio.__gdal_version__" }
)

$missing = @()
foreach ($c in $checks) {
    & $vPy -c $c.imp 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  [OK]      $($c.name)" -ForegroundColor Green
    } else {
        Write-Host "  [MISSING] $($c.name)" -ForegroundColor Red
        $missing += $c.name
    }
}

# ---------------------------------------------------------------------------
# 6. Write launchers
# ---------------------------------------------------------------------------

$batPath = Join-Path $repoRoot "run_flatcam.bat"
$batContent = @"
@echo off
setlocal
set "repo=%~dp0"
set "python=%repo%.venv\Scripts\python.exe"

if not exist "%python%" (
    echo FlatCAM's virtual environment was not found.
    echo Run setup_windows.ps1 from the repository first.
    pause
    exit /b 1
)

pushd "%repo%"
"%python%" "%repo%flatcam.py" %*
set "exit_code=%errorlevel%"
popd
exit /b %exit_code%
"@
[System.IO.File]::WriteAllText($batPath, $batContent, [System.Text.Encoding]::ASCII)

Write-Host ""
Write-Host "Created terminal launcher: run_flatcam.bat" -ForegroundColor Green

$shortcutScript = Join-Path $repoRoot "create_windows_shortcut.ps1"
& $shortcutScript

# ---------------------------------------------------------------------------
# 7. Summary
# ---------------------------------------------------------------------------

Write-Host ""
Write-Host "=== Setup Complete ===" -ForegroundColor Cyan

if ($missing.Count -gt 0) {
    Write-Host ""
    Write-Host "Missing packages: $($missing -join ', ')" -ForegroundColor Yellow
    Write-Host "Try installing individually:" -ForegroundColor Yellow
    foreach ($pkg in $missing) {
        Write-Host "  .\.venv\Scripts\python.exe -m pip install $pkg" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "To launch FlatCAM:" -ForegroundColor White
Write-Host "  Taskbar/desktop  FlatCAM.lnk"
Write-Host "  Terminal/debug   run_flatcam.bat"
Write-Host "  -- or from PowerShell --"
Write-Host "  .\.venv\Scripts\python.exe flatcam.py"
Write-Host ""
