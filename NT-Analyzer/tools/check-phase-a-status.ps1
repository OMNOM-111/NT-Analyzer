<#
.SYNOPSIS
    Check Phase B / Variant 1 bridge smoke-test status.

.DESCRIPTION
    Prints NinjaTrader process status, NTAnalyzerBridge log tail,
    queue state under NT-Analyzer\jobs, the latest failed job's
    error.json + result.partial.json (full diagnostic trail), and
    the latest done job's result.json header.
#>
[CmdletBinding()]
param(
    [string]$ProjectRoot,
    [string]$NinjaTraderUserDir = (Join-Path $env:USERPROFILE 'Documents\NinjaTrader 8')
)

$ErrorActionPreference = 'Stop'

if (-not $ProjectRoot) {
    $scriptDir = $PSScriptRoot
    if (-not $scriptDir) {
        $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    }
    $ProjectRoot = Split-Path -Parent $scriptDir
}

function Section($name) {
    Write-Host ''
    Write-Host "=== $name ===" -ForegroundColor Cyan
}

$jobs = Join-Path $ProjectRoot 'jobs'
$log = Join-Path $NinjaTraderUserDir 'log\NTAnalyzerBridge.log'

Section 'NinjaTrader process'
$nt = @(Get-Process -Name 'NinjaTrader' -ErrorAction SilentlyContinue)
if ($nt.Count -eq 0) {
    Write-Host 'NinjaTrader is NOT running.' -ForegroundColor Yellow
    Write-Host 'Start NinjaTrader after running 01_INSTALL_BRIDGE.cmd.'
} else {
    $nt | Select-Object Id, ProcessName, StartTime, MainWindowTitle | Format-Table -AutoSize
}

Section 'Bridge log'
if (Test-Path $log) {
    Write-Host "Log: $log"
    Write-Host ''
    Get-Content $log -Tail 80
} else {
    Write-Host "Missing log: $log" -ForegroundColor Yellow
    Write-Host 'If NinjaTrader was already running during install, fully close it and start it again.'
    Write-Host 'If the log is still missing after restart, external DLL loading did not work.'
}

Section 'Queue summary'
if (-not (Test-Path $jobs)) {
    Write-Host "Missing jobs directory: $jobs" -ForegroundColor Red
    exit 1
}

foreach ($sub in @('pending', 'running', 'done', 'failed', 'cancelled')) {
    $dir = Join-Path $jobs $sub
    $count = 0
    if (Test-Path $dir) {
        $count = @(Get-ChildItem $dir -Directory -Force | Where-Object { $_.Name -ne '.staging' }).Count
    }
    "{0,-10} {1}" -f $sub, $count
}

Section 'Recent jobs'
Get-ChildItem $jobs -Directory -Recurse -Depth 2 -Force |
    Where-Object { $_.Name -ne '.staging' } |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 20 FullName, LastWriteTime |
    Format-Table -AutoSize -Wrap

Section 'Latest job overall'
$allJobs = @()
foreach ($sub in @('done','failed','running','pending','cancelled')) {
    $dir = Join-Path $jobs $sub
    if (Test-Path $dir) {
        $allJobs += Get-ChildItem $dir -Directory -Force |
            Where-Object { $_.Name -ne '.staging' } |
            Select-Object @{n='Status';e={$sub}}, FullName, Name, LastWriteTime
    }
}
$latest = $allJobs | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $latest) {
    Write-Host 'No jobs yet.'
} else {
    Write-Host ("Job:    {0}" -f $latest.Name)
    Write-Host ("Status: {0}" -f $latest.Status)
    Write-Host ("Path:   {0}" -f $latest.FullName)
    if ($latest.Status -eq 'done') {
        $res = Join-Path $latest.FullName 'result.json'
        if (Test-Path $res) {
            try {
                $obj = Get-Content $res -Raw | ConvertFrom-Json
                Write-Host ''
                Write-Host '--- metrics ---'
                $obj.metrics | ConvertTo-Json -Depth 4
                $tradesCnt = if ($obj.trades) { $obj.trades.Count } else { 0 }
                Write-Host ("trades in result.json: {0}" -f $tradesCnt)
            } catch { Write-Host "result.json parse error: $_" -ForegroundColor Yellow }
        }
    } elseif ($latest.Status -eq 'failed') {
        $err = Join-Path $latest.FullName 'error.json'
        if (Test-Path $err) {
            Write-Host ''
            Write-Host '--- error.json ---'
            Get-Content $err
        }
        $partial = Join-Path $latest.FullName 'result.partial.json'
        if (Test-Path $partial) {
            Write-Host ''
            Write-Host '--- result.partial.json (verification_warnings) ---'
            try {
                $p = Get-Content $partial -Raw | ConvertFrom-Json
                $p.verification_warnings | ForEach-Object { "  $_" }
            } catch { Get-Content $partial -TotalCount 80 }
        }
    } elseif ($latest.Status -eq 'running') {
        $hb = Join-Path $latest.FullName 'heartbeat.json'
        if (Test-Path $hb) { Write-Host ''; Write-Host '--- heartbeat.json ---'; Get-Content $hb }
    }
}

Section 'Failed history (most recent 3)'
$failed = Join-Path $jobs 'failed'
if (Test-Path $failed) {
    $hist = Get-ChildItem $failed -Directory -Force |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 3
    if (-not $hist) { Write-Host 'No failed jobs.' }
    foreach ($f in $hist) {
        $err = Join-Path $f.FullName 'error.json'
        if (Test-Path $err) {
            try {
                $e = Get-Content $err -Raw | ConvertFrom-Json
                Write-Host ("  {0}  {1}: {2}" -f $f.Name, $e.error_type, ($e.message -split "`n" | Select-Object -First 1))
            } catch {
                Write-Host ("  {0}  (unreadable error.json)" -f $f.Name)
            }
        } else {
            Write-Host ("  {0}  (no error.json)" -f $f.Name)
        }
    }
} else {
    Write-Host 'No failed/ directory.'
}
