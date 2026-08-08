$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
& (Join-Path $ProjectRoot ".venv\Scripts\uvicorn.exe") roadmind.main:app --reload --host 127.0.0.1 --port 8000

