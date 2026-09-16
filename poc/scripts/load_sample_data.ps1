# Load a Kibana sample dataset via the public API. Idempotent.
# Usage: .\load_sample_data.ps1 [dataset]   (default: kibana_sample_data_logs)

[CmdletBinding()]
param(
    [string]$Dataset = "kibana_sample_data_logs"
)

$KibanaUrl = if ($env:KIBANA_URL) { $env:KIBANA_URL.TrimEnd("/") } else { "http://localhost:5601" }

Write-Host "[load_sample_data] target: $KibanaUrl  dataset: $Dataset"

# 1) Wait for Kibana ready (max 60s)
$deadline = (Get-Date).AddSeconds(60)
$ready = $false
while ((Get-Date) -lt $deadline) {
    try {
        $resp = Invoke-WebRequest -Uri "$KibanaUrl/api/status" -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop
        if ($resp.StatusCode -eq 200) { $ready = $true; break }
    } catch {}
    Start-Sleep -Seconds 2
}
if (-not $ready) {
    Write-Error "[load_sample_data] Kibana not ready after 60s at $KibanaUrl"
    exit 1
}
Write-Host "[load_sample_data] Kibana ready"

# 2) POST install
try {
    $resp = Invoke-WebRequest -Uri "$KibanaUrl/api/sample_data/$Dataset" `
        -Method POST `
        -Headers @{ "kbn-xsrf" = "true" } `
        -UseBasicParsing -ErrorAction Stop
    Write-Host "[load_sample_data] installed (HTTP $($resp.StatusCode))"
    exit 0
} catch [System.Net.WebException] {
    $code = 0
    if ($_.Exception.Response) { $code = [int]$_.Exception.Response.StatusCode }
    if ($code -eq 400) {
        Write-Host "[load_sample_data] already installed (HTTP 400 — treating as success)"
        exit 0
    }
    Write-Error "[load_sample_data] failed: HTTP $code — $($_.Exception.Message)"
    exit 1
} catch {
    # Newer PowerShell wraps as HttpRequestException
    $msg = $_.Exception.Message
    if ($msg -match "400") {
        Write-Host "[load_sample_data] already installed (HTTP 400 — treating as success)"
        exit 0
    }
    Write-Error "[load_sample_data] failed: $msg"
    exit 1
}
