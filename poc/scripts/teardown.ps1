# Tear down PoC: docker compose down -v (DESTROYS local ES data).

[CmdletBinding()]
param([switch]$Y)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$PocDir = Split-Path -Parent $ScriptDir
Set-Location $PocDir

Write-Host "[teardown] WARNING: this will destroy local Elasticsearch volumes (sample data, indices)."
if (-not $Y) {
    $confirm = Read-Host "继续？输入 y 确认"
    if ($confirm -ne "y" -and $confirm -ne "Y") {
        Write-Host "[teardown] aborted"
        exit 0
    }
}
docker compose down -v
if ($LASTEXITCODE -ne 0) {
    Write-Error "[teardown] docker compose down failed."
    exit 1
}
Write-Host "[teardown] done"
