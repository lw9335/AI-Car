$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
& $Python -m pytest $ProjectRoot
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
