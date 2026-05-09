<#
.SYNOPSIS
    Build and deploy NTAnalyzerBridge.dll into NinjaTrader 8.

.DESCRIPTION
    Bridge install script.
      1. Builds bridge\NTAnalyzerBridge.csproj (Debug by default).
      2. Copies NTAnalyzerBridge.dll into <NinjaTraderUserDir>\bin\Custom\.
         (NinjaTrader's documented Visual Studio AddOn deploy path.)
      3. Copies the example config to <NinjaTraderUserDir>\bin\Custom\NTAnalyzerBridge.config.json
         IF that file does not exist yet (never overwrites a hand-edited config).
      4. Ensures the queue layout exists under <ProjectRoot>\jobs\.

    No admin rights required.

    After this script you must restart NinjaTrader so it loads the new DLL,
    then check <NinjaTraderUserDir>\log\NTAnalyzerBridge.log.

.PARAMETER ProjectRoot
    Repository root (folder that contains bridge\, docs\, jobs\, ...).
    Defaults to the parent of this script's folder.

.PARAMETER NinjaTraderUserDir
    NinjaTrader 8 user directory. Default: %USERPROFILE%\Documents\NinjaTrader 8.

.PARAMETER Configuration
    MSBuild configuration. Default: Debug.
#>
[CmdletBinding()]
param(
    [string]$ProjectRoot,
    [string]$NinjaTraderUserDir = (Join-Path $env:USERPROFILE 'Documents\NinjaTrader 8'),
    [ValidateSet('Debug','Release')]
    [string]$Configuration     = 'Debug'
)

$ErrorActionPreference = 'Stop'

function Write-Step { param($msg) Write-Host "[install-bridge] $msg" -ForegroundColor Cyan }
function Write-Ok   { param($msg) Write-Host "[install-bridge] OK: $msg" -ForegroundColor Green }
function Write-Warn { param($msg) Write-Host "[install-bridge] WARN: $msg" -ForegroundColor Yellow }

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

$bridgeDir = Join-Path $ProjectRoot 'bridge'
$csproj    = Join-Path $bridgeDir   'NTAnalyzerBridge.csproj'
$exampleCfg= Join-Path $bridgeDir   'NTAnalyzerBridge.config.example.json'

if (-not (Test-Path $csproj))     { throw "csproj not found: $csproj" }
if (-not (Test-Path $exampleCfg)) { throw "config example not found: $exampleCfg" }
if (-not (Test-Path $NinjaTraderUserDir)) {
    throw "NinjaTrader user dir not found: $NinjaTraderUserDir (pass -NinjaTraderUserDir)"
}

# Pre-flight: if NinjaTrader is running, the deployed DLL is locked AND
# even if it weren't, the running process is still bound to the OLD AddOn
# assembly. Abort upfront with a clear message instead of failing on Copy-Item.
$ntProc = @(Get-Process -Name 'NinjaTrader' -ErrorAction SilentlyContinue)
if ($ntProc.Count -gt 0) {
    $pids = ($ntProc | ForEach-Object { $_.Id }) -join ', '
    Write-Host ''
    Write-Host '###############################################################' -ForegroundColor Yellow
    Write-Host "#  NinjaTrader 8 is currently RUNNING (PID $pids)." -ForegroundColor Yellow
    Write-Host '#  The deployed DLL would be file-locked by NT, AND a running' -ForegroundColor Yellow
    Write-Host '#  NinjaTrader does not pick up replaced AddOn DLLs without a' -ForegroundColor Yellow
    Write-Host '#  full restart. Save your NinjaScript work, fully close NT,' -ForegroundColor Yellow
    Write-Host '#  then run this script again.' -ForegroundColor Yellow
    Write-Host '###############################################################' -ForegroundColor Yellow
    Write-Host ''
    throw "NinjaTrader is running (PID $pids) - close it before installing the bridge DLL"
}

# 1. Build
Write-Step "building $csproj ($Configuration)"
& dotnet build $csproj -c $Configuration | Write-Host
if ($LASTEXITCODE -ne 0) { throw "dotnet build failed (exit $LASTEXITCODE)" }

$builtDll = Join-Path $bridgeDir "bin\$Configuration\NTAnalyzerBridge.dll"
if (-not (Test-Path $builtDll)) { throw "build succeeded but DLL not found at $builtDll" }
Write-Ok "built $builtDll"

# 2. Deploy DLL
$customDir = Join-Path $NinjaTraderUserDir 'bin\Custom'
if (-not (Test-Path $customDir)) { throw "missing $customDir - is NinjaTrader 8 installed for this user?" }

$dllDst = Join-Path $customDir 'NTAnalyzerBridge.dll'
Write-Step "copying DLL -> $dllDst"
Copy-Item -Path $builtDll -Destination $dllDst -Force
Write-Ok "DLL deployed"

# 3. Deploy config (do NOT overwrite an existing one)
$cfgDst = Join-Path $customDir 'NTAnalyzerBridge.config.json'
if (Test-Path $cfgDst) {
    Write-Warn "config already exists, leaving as-is: $cfgDst"
} else {
    Copy-Item -Path $exampleCfg -Destination $cfgDst
    Write-Ok "config installed: $cfgDst"
    Write-Warn "open the file and verify project_root / ninjatrader_user_dir match this machine"
}

# 4. Queue layout
$jobsDir = Join-Path $ProjectRoot 'jobs'
foreach ($sub in @('pending','pending\.staging','running','done','failed','cancelled')) {
    $p = Join-Path $jobsDir $sub
    if (-not (Test-Path $p)) {
        New-Item -ItemType Directory -Force -Path $p | Out-Null
        Write-Ok "created $p"
    }
}

Write-Host ''
Write-Host '[install-bridge] DONE. Next steps:' -ForegroundColor Cyan
Write-Host '  1. Start NinjaTrader 8.'
Write-Host "  2. Check log: $(Join-Path $NinjaTraderUserDir 'log\NTAnalyzerBridge.log')"
Write-Host '     Expect: "config loaded ...", "whitelisted strategies: N",'
Write-Host '             "SampleMACrossOver found in whitelist",'
Write-Host '             "Queue watcher started ...".'
Write-Host '  3. Run tools\enqueue-smoke-job.ps1 to drop a test job into pending/.'
