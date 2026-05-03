$ErrorActionPreference = "Stop"

$backendPath = Join-Path $PSScriptRoot "sentinel-backend"
$frontendPath = Join-Path $PSScriptRoot "sentinel-frontend"

Write-Host "Starting Prahari local development stack..." -ForegroundColor Cyan
Write-Host "Backend:  http://localhost:8000" -ForegroundColor Cyan
Write-Host "Frontend: http://localhost:5173" -ForegroundColor Cyan
Write-Host ""

$backendCommand = "Set-Location -LiteralPath '$backendPath'; Write-Host 'Prahari backend: http://localhost:8000' -ForegroundColor Cyan; uvicorn app.main:app --reload"
$frontendCommand = "Set-Location -LiteralPath '$frontendPath'; Write-Host 'Prahari frontend: http://localhost:5173' -ForegroundColor Cyan; npm run dev"

Start-Process powershell.exe -ArgumentList @("-NoExit", "-Command", $backendCommand)
Start-Process powershell.exe -ArgumentList @("-NoExit", "-Command", $frontendCommand)

Write-Host "Opened backend and frontend in two new PowerShell windows." -ForegroundColor Green
Write-Host "Keep those windows open while developing." -ForegroundColor Yellow
