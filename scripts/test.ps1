$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
& (Join-Path $ProjectRoot ".venv\Scripts\pytest.exe") $ProjectRoot

