# End-to-end PoC setup: docker compose up + wait healthy + load sample data + .env scaffolding.
# Idempotent. Run from anywhere — the script cd's into poc/.

[CmdletBinding()]
param()

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$PocDir = Split-Path -Parent $ScriptDir
Set-Location $PocDir

Write-Host "[setup_demo] working directory: $PocDir"

# 1) Prereqs
try { docker --version | Out-Null } catch {
    Write-Error "[setup_demo] Docker not found. Install Docker Desktop and start it."
    exit 1
}
try {
    $py = (python --version) 2>&1
    if ($py -notmatch "Python 3\.(1[0-9]|[2-9][0-9])") {
        Write-Warning "[setup_demo] Python 3.10+ recommended. Got: $py"
    }
} catch {
    Write-Error "[setup_demo] Python not found. Install Python 3.10+."
    exit 1
}

# 2) docker compose up
Write-Host "[setup_demo] starting Elasticsearch + Kibana..."
docker compose up -d
if ($LASTEXITCODE -ne 0) {
    Write-Error "[setup_demo] docker compose failed. Check 'docker ps' and logs."
    exit 1
}

# 3) Wait for ES yellow status
Write-Host "[setup_demo] waiting for Elasticsearch (yellow status, up to 60s)..."
$ok = $false
for ($i = 0; $i -lt 30; $i++) {
    try {
        $resp = Invoke-RestMethod -Uri "http://localhost:9200/_cluster/health?wait_for_status=yellow&timeout=2s" -TimeoutSec 5 -ErrorAction Stop
        if ($resp.status -in @("yellow", "green")) { $ok = $true; break }
    } catch {}
    Start-Sleep -Seconds 2
}
if (-not $ok) {
    Write-Error "[setup_demo] Elasticsearch did not become healthy in 60s. Check 'docker logs rst-elastic-ai-copilot-poc-es'."
    exit 1
}
Write-Host "[setup_demo] Elasticsearch healthy"

# 4) Wait for Kibana
Write-Host "[setup_demo] waiting for Kibana (up to 120s)..."
$ok = $false
for ($i = 0; $i -lt 60; $i++) {
    try {
        $resp = Invoke-WebRequest -Uri "http://localhost:5601/api/status" -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop
        if ($resp.StatusCode -eq 200) { $ok = $true; break }
    } catch {}
    Start-Sleep -Seconds 2
}
if (-not $ok) {
    Write-Error "[setup_demo] Kibana did not become ready in 120s. Check 'docker logs rst-elastic-ai-copilot-poc-kibana'."
    exit 1
}
Write-Host "[setup_demo] Kibana ready"

# 5) Load sample data (idempotent)
& "$ScriptDir\load_sample_data.ps1"
if ($LASTEXITCODE -ne 0) {
    Write-Error "[setup_demo] sample data load failed."
    exit 1
}

# 6) .env scaffolding
$envPath = Join-Path $PocDir ".env"
$envExamplePath = Join-Path $PocDir ".env.example"
Write-Host ""
if (-not (Test-Path $envPath)) {
    Copy-Item $envExamplePath $envPath
    Write-Host "[setup_demo] 已创建 .env（复制自 .env.example）"
    Write-Host "[setup_demo] 请编辑 .env 填入 LLM_API_KEY 和 LLM_MODEL（火山方舟接入点 ID）"
    Write-Host "[setup_demo] 然后跑：python -m uvicorn backend.main:app --reload --port 8000"
} else {
    Write-Host "[setup_demo] .env 已存在，跳过"
    Write-Host "[setup_demo] 启动后端：python -m uvicorn backend.main:app --reload --port 8000"
}
