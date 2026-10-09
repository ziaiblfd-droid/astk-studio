#requires -Version 5.1
<#
.SYNOPSIS
  Stage the ASTK-native GO-BP backend and atomically deploy an idle service.
.DESCRIPTION
  The server helper creates a new release, runs tests, checks the queue again,
  and rolls back on failed health checks. Existing releases are never edited.
  Publish the Cloudflare frontend separately with deploy-worker.ps1.
#>
param(
  [string]$ReleaseId = ("native-bp-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ($ReleaseId -notmatch '^[a-zA-Z0-9-]+$') { throw "Invalid release identifier" }
$Server = "yushiye@172.18.236.93"
$Key = Join-Path $env:USERPROFILE ".ssh\astk_web_deploy_ed25519"
$Root = Split-Path $PSScriptRoot -Parent
$Stage = "/home/yushiye/astk-web/.enrichment-stage-$ReleaseId"
$Files = @(
  "backend/server.py", "backend/downstream.py", "backend/native_enrichment.py",
  "backend/native_enrichment.R", "index.html", "downstream.js", "downstream.css",
  "i18n.js", "scripts/deploy-enrichment-release.sh",
  "tests/native_enrichment_contract.R", "tests/native_enrichment_reference.py",
  "tests/native_enrichment_compare_reference.R"
)
if (-not (Test-Path -LiteralPath $Key)) { throw "SSH key not found: $Key" }
foreach ($File in $Files) {
  if (-not (Test-Path -LiteralPath (Join-Path $Root $File))) { throw "Missing file: $File" }
}
ssh -i $Key -o BatchMode=yes -o ConnectTimeout=15 $Server "test ! -e $Stage && mkdir -p $Stage/backend $Stage/scripts $Stage/tests"
if ($LASTEXITCODE -ne 0) { throw "Staging setup failed; no deployment performed" }
foreach ($File in $Files) {
  scp -i $Key (Join-Path $Root $File) "${Server}:$Stage/$File"
  if ($LASTEXITCODE -ne 0) { throw "Upload failed: $File" }
}
$Tests = @(Get-ChildItem -LiteralPath (Join-Path $Root "tests") -Filter "test_*.py")
foreach ($Test in $Tests) {
  scp -i $Key $Test.FullName "${Server}:$Stage/tests/$($Test.Name)"
  if ($LASTEXITCODE -ne 0) { throw "Test upload failed: $($Test.Name)" }
}
ssh -i $Key -o BatchMode=yes $Server "bash $Stage/scripts/deploy-enrichment-release.sh $Stage $ReleaseId"
if ($LASTEXITCODE -ne 0) { throw "Deployment failed or backend was busy. Previous release retained." }
Write-Host "Backend deployed: $ReleaseId"
