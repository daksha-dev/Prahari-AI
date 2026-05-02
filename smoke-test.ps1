$ErrorActionPreference = "Continue"

$backendUrl = "http://localhost:8000"
$passed = 0
$failed = 0

function Pass($name) {
    $script:passed++
    Write-Host "PASS $name" -ForegroundColor Green
}

function Fail($name, $reason) {
    $script:failed++
    Write-Host "FAIL $name - $reason" -ForegroundColor Red
}

function Test-Get($name, $path) {
    try {
        $null = Invoke-RestMethod -Method Get -Uri "$backendUrl$path" -TimeoutSec 10
        Pass $name
    } catch {
        Fail $name $_.Exception.Message
    }
}

function Test-PostJson($name, $path, $body) {
    try {
        $json = $body | ConvertTo-Json -Depth 10 -Compress
        $null = Invoke-RestMethod -Method Post -Uri "$backendUrl$path" -ContentType "application/json" -Body $json -TimeoutSec 15
        Pass $name
    } catch {
        Fail $name $_.Exception.Message
    }
}

Write-Host "Running Sentinel smoke tests against $backendUrl" -ForegroundColor Cyan

Test-Get "healthz" "/healthz"
Test-Get "devices" "/api/devices"
Test-Get "network summary" "/api/network-summary"
Test-Get "thermostat detail" "/api/devices/192.168.50.21"
Test-Get "thermostat evidence" "/api/devices/192.168.50.21/evidence"
Test-PostJson "scenario slow_drift" "/api/scenario" @{ name = "slow_drift" }

try {
    $tempFile = [System.IO.Path]::GetTempFileName()
    $chatBody = '{"messages":[{"role":"user","content":"What devices should I worry about?"}],"language":"en"}'
    Set-Content -LiteralPath $tempFile -Value $chatBody -NoNewline -Encoding UTF8
    $chatOutput = & curl.exe -sS -N --max-time 20 -X POST "$backendUrl/api/chat" -H "Content-Type: application/json" --data-binary "@$tempFile"
    if ($LASTEXITCODE -eq 0 -and $chatOutput -match "data:") {
        Pass "chat SSE"
    } else {
        Fail "chat SSE" "SSE stream did not contain data events"
    }
} catch {
    Fail "chat SSE" $_.Exception.Message
} finally {
    if ($tempFile -and (Test-Path $tempFile)) {
        Remove-Item -LiteralPath $tempFile -Force
    }
}

Write-Host ""
if ($failed -eq 0) {
    Write-Host "Summary: $passed passed, $failed failed" -ForegroundColor Green
} else {
    Write-Host "Summary: $passed passed, $failed failed" -ForegroundColor Red
}
