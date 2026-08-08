$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VirtualEnv = Join-Path $ProjectRoot ".venv"
$Python = Join-Path $VirtualEnv "Scripts\python.exe"

if (-not (Test-Path -LiteralPath $VirtualEnv)) {
    python -m venv $VirtualEnv
}

& $Python -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $Python -m pip install -e "${ProjectRoot}[dev]"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host "RoadMind development environment is ready."
