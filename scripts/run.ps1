$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
& $Python -m uvicorn roadmind.main:app --reload --host 127.0.0.1 --port 8000
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
