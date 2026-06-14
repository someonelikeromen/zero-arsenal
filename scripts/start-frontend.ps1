# start-frontend.ps1 — Launch ZeroArsenal frontend in a new PowerShell window
# Usage: .\scripts\start-frontend.ps1  or double-click start-frontend.cmd

param()

$Root     = Split-Path -Parent $PSScriptRoot
$Frontend = Join-Path $Root 'frontend'
$Title    = 'ZA-Frontend'

if (-not (Test-Path (Join-Path $Frontend 'package.json'))) {
    Write-Error "frontend/package.json not found: $Frontend"
    exit 1
}

$inner = @"
Set-Location -LiteralPath '$Frontend'
`$host.UI.RawUI.WindowTitle = '$Title'
Write-Host '[$Title] dir: $Frontend' -ForegroundColor Cyan
Write-Host '[$Title] UI: http://localhost:5173' -ForegroundColor DarkGray
Write-Host '[$Title] Ctrl+C to stop' -ForegroundColor DarkGray
npm run dev
"@

Start-Process powershell.exe -ArgumentList '-NoExit', '-NoProfile', '-Command', $inner
Write-Host "[start-frontend] New window launched ($Title)" -ForegroundColor Green
