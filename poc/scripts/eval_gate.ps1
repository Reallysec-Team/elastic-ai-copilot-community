# Local eval gate — run the eval and exit nonzero if pass rate is below threshold.
# Mirrors what the GitHub Actions workflow does, for pre-push verification.
#
# Usage:
#   .\scripts\eval_gate.ps1                # default threshold 0.9 (90%)
#   .\scripts\eval_gate.ps1 -Threshold 0.85
#   .\scripts\eval_gate.ps1 -Case top-urls -Threshold 1.0

[CmdletBinding()]
param(
    [double]$Threshold = 0.9,
    [string]$Case = ""
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$PocDir = Split-Path -Parent $ScriptDir
Set-Location $PocDir

Write-Host "[eval_gate] threshold: $Threshold"

$args = @("-m", "eval.run", "--gate", $Threshold.ToString())
if ($Case) { $args += @("--case", $Case) }

python @args
exit $LASTEXITCODE
