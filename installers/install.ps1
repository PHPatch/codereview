# CodeReview — installer for Windows (PowerShell).
#
#   irm https://phpatch.com/codereview/install.ps1 | iex
#
# What it does, in plain words:
#   1. checks you have Python 3.11 or newer (CodeReview needs it);
#   2. installs the `codereview-ai` package from PyPI in its own
#      isolated environment (pipx if you have it, otherwise a
#      private virtual environment under %LOCALAPPDATA%) — your
#      system Python and other tools are never touched;
#   3. tells you exactly what to do if the `codereview` command
#      is not found afterwards (it is a PATH setting, printed
#      step by step below).
#
# Nothing is installed system-wide and no administrator rights
# are needed. To remove CodeReview later, delete the environment
# folder printed at the end.
#
# Pre-launch note: this script installs the published package
# `codereview-ai` from PyPI. Until the package is published,
# testers can point the installer at another source by setting
# CODEREVIEW_INSTALL_SOURCE (a local checkout path or an exact
# package spec) before running it.

$ErrorActionPreference = 'Stop'

$Package = if ($env:CODEREVIEW_INSTALL_SOURCE) { $env:CODEREVIEW_INSTALL_SOURCE } else { 'codereview-ai' }
$VenvDir = if ($env:CODEREVIEW_VENV) { $env:CODEREVIEW_VENV } else { Join-Path $env:LOCALAPPDATA 'codereview-venv' }

function Fail($msg) { Write-Host "install: $msg" -ForegroundColor Red; exit 1 }

# --- 1. find a Python new enough --------------------------------
$Python = $null
foreach ($cand in @('py', 'python')) {
    try {
        $v = & $cand -c "import sys; print(sys.version_info >= (3, 11))" 2>$null
        if ($v -match 'True') { $Python = $cand; break }
    } catch { }
}
if (-not $Python) {
    Fail "Python 3.11 or newer was not found on this machine.`nCodeReview needs it. Install it from https://www.python.org/downloads/ (tick 'Add python.exe to PATH' in the installer), then run this installer again."
}
Write-Host "Found Python ($(& $Python --version))."

# --- 2. install, isolated ---------------------------------------
$Exe = $null
if (Get-Command pipx -ErrorAction SilentlyContinue) {
    Write-Host 'Installing CodeReview with pipx (isolated environment)...'
    pipx install --force $Package | Out-Null
    $PipxBin = (pipx environment --value PIPX_BIN_DIR)
    $Exe = Join-Path $PipxBin 'codereview.exe'
} else {
    Write-Host "Installing CodeReview into its own environment at $VenvDir ..."
    & $Python -m venv $VenvDir
    $VenvPython = Join-Path $VenvDir 'Scripts\python.exe'
    & $VenvPython -m pip install --quiet --upgrade pip
    & $VenvPython -m pip install --quiet $Package
    $Exe = Join-Path $VenvDir 'Scripts\codereview.exe'
}
if (-not (Test-Path $Exe)) {
    Fail 'the install finished but the codereview command was not created - please report this (see SUPPORT in the package docs).'
}

# --- 3. say what happened ---------------------------------------
Write-Host ''
Write-Host "CodeReview is installed: $Exe"
$BinDir = Split-Path $Exe
if (($env:PATH -split ';') -notcontains $BinDir) {
    Write-Host "If typing 'codereview' says the command is not found, add its folder to your PATH:"
    Write-Host "  1. Press the Windows key, type 'environment variables', open 'Edit the system environment variables'"
    Write-Host "  2. Click 'Environment Variables', select 'Path' under your user, click 'Edit', then 'New'"
    Write-Host "  3. Paste this folder: $BinDir"
    Write-Host '  4. Click OK everywhere and open a NEW PowerShell window'
}
Write-Host 'Next steps:'
Write-Host '  1. codereview setup          - pick your AI providers (you bring your own keys)'
Write-Host '  2. codereview doctor --plain - check every seat answers, in plain words'
Write-Host '  3. in a git repo: codereview - your first review'
