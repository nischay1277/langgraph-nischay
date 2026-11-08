$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$atlasPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $atlasPython)) {
    Write-Host 'Create the environment first: python -m venv .venv'
    Write-Host 'Then run: .\.venv\Scripts\python.exe -m pip install -r requirements.lock'
    exit 1
}
Write-Host 'Incident Atlas: http://127.0.0.1:8765'
Write-Host 'Press Ctrl+C to stop. Documents remain in data/atlas.sqlite3.'
& $atlasPython -m incident_atlas
