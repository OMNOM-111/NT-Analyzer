#Requires -Version 5.1
<#
.SYNOPSIS
  Isolated PostgreSQL acceptance runner for StratForge (Windows / PowerShell).

.DESCRIPTION
  Applies the additive migration set (1..N) to an isolated, non-Production
  PostgreSQL instance and runs the PostgreSQL-dependent acceptance suite:
  migrations + checksum, row-level-security workspace isolation, UUID identity
  backfill, release-center tables, and NinjaTrader resource leases / workers.

  It reads the two DSNs from the environment (or from
  deploy/testing/postgres-acceptance.env if present). If they are absent it
  exits with a clear BLOCKED message instead of pretending to pass.

.NOTES
  Never point these DSNs at a Production database — the suite truncates tables.
#>
[CmdletBinding()]
param(
  [string]$EnvFile = (Join-Path $PSScriptRoot 'postgres-acceptance.env')
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..' '..')).Path

if (Test-Path $EnvFile) {
  Get-Content $EnvFile | ForEach-Object {
    if ($_ -match '^\s*([A-Z0-9_]+)\s*=\s*(.+)\s*$') {
      [System.Environment]::SetEnvironmentVariable($matches[1], $matches[2], 'Process')
    }
  }
}

$adminUrl = $env:STRATFORGE_TEST_POSTGRES_ADMIN_URL
$appUrl   = $env:STRATFORGE_TEST_POSTGRES_URL
if (-not $adminUrl -or -not $appUrl) {
  Write-Host 'BLOCKED - EXTERNAL TEST DATABASE REQUIRED' -ForegroundColor Yellow
  Write-Host 'Set STRATFORGE_TEST_POSTGRES_ADMIN_URL and STRATFORGE_TEST_POSTGRES_URL'
  Write-Host '(see postgres-acceptance.env.example and provision-test-postgres.sql).'
  exit 3
}

Push-Location $repoRoot
try {
  Write-Host '== Applying migrations to the isolated acceptance database ==' -ForegroundColor Cyan
  python -c "from app.production_storage.core import MigrationRunner; import json; print(json.dumps(MigrationRunner('$adminUrl').apply()))"
  if ($LASTEXITCODE -ne 0) { throw 'migration apply failed' }

  Write-Host '== Running PostgreSQL-dependent acceptance suite ==' -ForegroundColor Cyan
  python -m pytest -q -p no:cacheprovider `
    tests/test_stage8_postgresql.py `
    tests/test_production_storage.py `
    tests/test_production_workers.py
  exit $LASTEXITCODE
}
finally {
  Pop-Location
}
