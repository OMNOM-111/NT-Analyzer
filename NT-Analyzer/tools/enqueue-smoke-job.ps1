<#
.SYNOPSIS
    Drop a Phase-B Variant 1 smoke-test job into the file queue.

.DESCRIPTION
    Creates a single job in <ProjectRoot>\jobs\ following the canonical
    two-step protocol from docs\job-schema.md:

      1. Build job.json inside <jobs>\pending\.staging\<job_id>\ via
         write-temp-then-rename (job.json.tmp -> job.json).
      2. Atomically Directory.Move staging\<job_id>\ -> pending\<job_id>\.

    The bridge AddOn (running inside NinjaTrader) should claim it and:
      - on success: move it to done\<job_id>\ with result.json carrying
        source.rd_variant_used = "1_strategy_analyzer";
      - on failure: move it to failed\<job_id>\ with
        error.json (error_type="variant1_unavailable") plus
        result.partial.json containing the full diagnostic trail.

.PARAMETER ProjectRoot
    Defaults to the parent of this script's folder.

.PARAMETER JobId
    Override the auto-generated job_id.

.PARAMETER ClassName
    Strategy class_name to put into job.json. Default: SampleMACrossOver.

.PARAMETER Instrument
    Default: MES 06-26.
#>
[CmdletBinding()]
param(
    [string]$ProjectRoot,
    [string]$JobId,
    [string]$ClassName   = 'SampleMACrossOver',
    [string]$Instrument  = 'MES 06-26'
)

$ErrorActionPreference = 'Stop'

function Get-ScriptDirectory {
    if (-not [string]::IsNullOrWhiteSpace($PSScriptRoot)) {
        return $PSScriptRoot
    }
    if (-not [string]::IsNullOrWhiteSpace($PSCommandPath)) {
        return Split-Path -Parent $PSCommandPath
    }
    if ($MyInvocation.MyCommand -and -not [string]::IsNullOrWhiteSpace($MyInvocation.MyCommand.Path)) {
        return Split-Path -Parent $MyInvocation.MyCommand.Path
    }
    return $null
}

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $scriptDir = Get-ScriptDirectory
    if ([string]::IsNullOrWhiteSpace($scriptDir)) {
        # Last resort for double-click/cmd launch: each .cmd does cd /d "%~dp0",
        # so current directory is the project root.
        $ProjectRoot = (Get-Location).Path
    } else {
        $ProjectRoot = Split-Path -Parent $scriptDir
    }
}

if (-not $JobId) {
    $JobId = 'smoke_' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ')
}

$jobsDir   = Join-Path $ProjectRoot 'jobs'
$pending   = Join-Path $jobsDir     'pending'
$staging   = Join-Path $pending     '.staging'
$stagingJob= Join-Path $staging     $JobId
$pendingJob= Join-Path $pending     $JobId

if (Test-Path $pendingJob) { throw "pending\$JobId already exists" }
if (Test-Path $stagingJob) { Remove-Item -Recurse -Force $stagingJob }

New-Item -ItemType Directory -Force -Path $stagingJob | Out-Null

$nowUtc = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")
$job = [ordered]@{
    schema_version = '0.1'
    job_id         = $JobId
    created_at_utc = $nowUtc
    kind           = 'historical_backtest'
    strategy = [ordered]@{
        class_name        = $ClassName
        source_file_hint  = ''
        # Explicit Fast/Slow so we don't depend on NinjaScript SetDefaults
        # actually having run on the CLR-instantiated template.
        # SampleMACrossOver canonical defaults: Fast=10, Slow=25.
        parameters        = [ordered]@{
            Fast = 10
            Slow = 25
        }
    }
    instrument = $Instrument
    timeframe  = [ordered]@{
        bars_period_type = 'Minute'
        value            = 1
    }
    period = [ordered]@{
        from_utc = '2026-03-12T00:00:00Z'
        to_utc   = '2026-04-24T00:00:00Z'
    }
    execution = [ordered]@{
        calculate             = 'OnBarClose'
        is_tick_replay        = $false
        order_fill_resolution = 'Standard'
        slippage_ticks        = 0
        commission            = 0.0
        session_template      = 'CME US Index Futures RTH'
        timezone              = 'UTC'
    }
}

$json = $job | ConvertTo-Json -Depth 20

# Step 1: write-temp-then-rename inside staging
$jobJson = Join-Path $stagingJob 'job.json'
$tmpJson = $jobJson + '.tmp'
Set-Content -Path $tmpJson -Value $json -Encoding UTF8 -NoNewline
Move-Item  -Path $tmpJson -Destination $jobJson

# Step 2: atomic Directory.Move staging\<id> -> pending\<id>
[System.IO.Directory]::Move($stagingJob, $pendingJob)

Write-Host "[enqueue-smoke-job] job created: $pendingJob" -ForegroundColor Green
Write-Host '[enqueue-smoke-job] expected outcome (Phase B / Variant 1):'
Write-Host '  on success:'
Write-Host "    $(Join-Path $jobsDir ('done\' + $JobId + '\result.json'))"
Write-Host '    with: source.rd_variant_used = "1_strategy_analyzer"'
Write-Host '  on failure:'
Write-Host "    $(Join-Path $jobsDir ('failed\' + $JobId + '\error.json'))"
Write-Host "    +   $(Join-Path $jobsDir ('failed\' + $JobId + '\result.partial.json'))"
Write-Host '    with: error_type = "variant1_unavailable" + diagnostic trail'
Write-Host ''
Write-Host '[enqueue-smoke-job] If nothing happens within ~10 seconds, check:'
Write-Host "  $(Join-Path $env:USERPROFILE 'Documents\NinjaTrader 8\log\NTAnalyzerBridge.log')"
