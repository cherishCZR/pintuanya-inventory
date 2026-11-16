$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $project
& "$project\.venv\Scripts\python.exe" -m pintuanya_inventory demo
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& "$project\.venv\Scripts\python.exe" -m pintuanya_inventory status --mode demo
