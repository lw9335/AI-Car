$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VirtualEnv = Join-Path $ProjectRoot ".venv"

if (-not (Test-Path -LiteralPath $VirtualEnv)) {
    python -m venv $VirtualEnv
}

& (Join-Path $VirtualEnv "Scripts\python.exe") -m pip install --upgrade pip
& (Join-Path $VirtualEnv "Scripts\python.exe") -m pip install -e "$ProjectRoot[dev]"
Write-Host "RoadMind development environment is ready."

