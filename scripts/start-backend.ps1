# start-backend.ps1 — Launch ZeroArsenal backend in a new PowerShell window
# Usage: .\scripts\start-backend.ps1  or double-click start-backend.cmd

param()

$Root   = Split-Path -Parent $PSScriptRoot
$Python = 'C:\Python313\python.exe'
$Title  = 'ZA-Backend'

if (-not (Test-Path (Join-Path $Root 'backend\main.py'))) {
    Write-Error "backend/main.py not found: $Root"
    exit 1
}

$inner = @"
Set-Location -LiteralPath '$Root'
`$host.UI.RawUI.WindowTitle = '$Title'
Write-Host '[$Title] dir: $Root' -ForegroundColor Cyan
Write-Host '[$Title] API docs: http://localhost:8000/docs' -ForegroundColor DarkGray
Write-Host '[$Title] Ctrl+C to stop' -ForegroundColor DarkGray
& '$Python' -m backend.main
"@

Start-Process powershell.exe -ArgumentList '-NoExit', '-NoProfile', '-Command', $inner
Write-Host "[start-backend] New window launched ($Title)" -ForegroundColor Green
