$ErrorActionPreference = "Continue"

$backendUrl = "http://localhost:8000"
$deviceId = "192.168.50.21"

function Get-Severity($trust) {
    if ($trust -lt 35) { return @{ Label = "CRITICAL"; Color = "Red" } }
    if ($trust -lt 50) { return @{ Label = "AT_RISK"; Color = "Yellow" } }
    if ($trust -lt 70) { return @{ Label = "WATCH"; Color = "Yellow" } }
    return @{ Label = "NORMAL"; Color = "Green" }
}

function Get-Bar($trust) {
    $width = 30
    $filled = [Math]::Round(($trust / 100) * $width)
    $filled = [Math]::Max(0, [Math]::Min($width, $filled))
    return ("#" * $filled) + ("-" * ($width - $filled))
}

Write-Host "Switching demo scenario to slow_drift..." -ForegroundColor Cyan
try {
    $body = @{ name = "slow_drift" } | ConvertTo-Json -Compress
    $null = Invoke-RestMethod -Method Post -Uri "$backendUrl/api/scenario" -ContentType "application/json" -Body $body -TimeoutSec 15
    Write-Host "Scenario switched. Watching Smart Thermostat ($deviceId) for 90 seconds." -ForegroundColor Green
} catch {
    Write-Host "Could not switch scenario: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

for ($elapsed = 0; $elapsed -le 90; $elapsed += 10) {
    try {
        $detail = Invoke-RestMethod -Method Get -Uri "$backendUrl/api/devices/$deviceId" -TimeoutSec 10
        $trust = [double]$detail.current_trust
        $severity = Get-Severity $trust
        $bar = Get-Bar $trust
        Write-Host ("T+{0,2}s  Trust {1,6:N2}  [{2}]  " -f $elapsed, $trust, $bar) -NoNewline -ForegroundColor Cyan
        Write-Host $severity.Label -ForegroundColor $severity.Color
    } catch {
        Write-Host "T+$elapsed s  Failed to fetch thermostat: $($_.Exception.Message)" -ForegroundColor Red
    }

    if ($elapsed -lt 90) {
        Start-Sleep -Seconds 10
    }
}

Write-Host ""
Write-Host "Asking Prahari chat: What is wrong with the thermostat?" -ForegroundColor Cyan

try {
    $tempFile = [System.IO.Path]::GetTempFileName()
    $chatBody = '{"messages":[{"role":"user","content":"What is wrong with the thermostat?"}],"language":"en"}'
    Set-Content -LiteralPath $tempFile -Value $chatBody -NoNewline -Encoding UTF8
    & curl.exe -N -X POST "$backendUrl/api/chat" -H "Content-Type: application/json" --data-binary "@$tempFile"
    Write-Host ""
    Write-Host "Demo check complete." -ForegroundColor Green
} catch {
    Write-Host "Chat check failed: $($_.Exception.Message)" -ForegroundColor Red
} finally {
    if ($tempFile -and (Test-Path $tempFile)) {
        Remove-Item -LiteralPath $tempFile -Force
    }
}
