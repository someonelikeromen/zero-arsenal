# start-all.ps1 — Launch backend and frontend each in their own PowerShell window
# Usage: .\scripts\start-all.ps1  or double-click start-all.cmd

param()

$ScriptsDir = $PSScriptRoot

Write-Host "[start-all] Starting backend..." -ForegroundColor Cyan
& (Join-Path $ScriptsDir 'start-backend.ps1')
Start-Sleep -Seconds 1

Write-Host "[start-all] Starting frontend..." -ForegroundColor Cyan
& (Join-Path $ScriptsDir 'start-frontend.ps1')

Write-Host "[start-all] Both windows launched." -ForegroundColor Green
Write-Host "  Backend: http://localhost:8000/docs" -ForegroundColor DarkGray
Write-Host "  Frontend: http://localhost:5173" -ForegroundColor DarkGray
