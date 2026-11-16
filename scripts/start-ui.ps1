$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $project
if (-not (Test-Path -LiteralPath "$project\.venv\Scripts\python.exe")) { throw 'Run install-windows.cmd first.' }
& "$project\.venv\Scripts\python.exe" "$project\scripts\launch.py" --view inventory
exit $LASTEXITCODE
