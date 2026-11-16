$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $project
& "$project/.venv/Scripts/python.exe" "$project/scripts/release.py" build
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
