<#
.SYNOPSIS
    Legacy AI Lab research launcher; not the normal StratForge startup.

.DESCRIPTION
    Historical best-effort startup for the local research stack. The accepted
    Agent World workflow uses tools/start-canonical-local.ps1 and AI Center.

    NinjaTrader is NOT started by default (prevents login lockouts after reboot).
    Pass -StartNinjaTrader only when you intentionally want the process launched;
    you must still sign in to NinjaTrader manually.

    Configure custom paths via environment variables or ai_lab/bootstrap.json:
      NINJATRADER_EXE, LM_STUDIO_EXE, LMS_CLI
#>
[CmdletBinding()]
param(
    [int]$Port = 8765,
    [switch]$NoBrowser,
    [switch]$SkipDependencyStart,
    # Dangerous after reboot: opens NT login dialog and can lock the account.
    # Opt-in only, and still requires NTA_ALLOW_AUTOSTART_NINJATRADER=1 in Python paths.
    [switch]$StartNinjaTrader
)

$ErrorActionPreference = 'Stop'
Write-Warning 'Legacy AI Lab only. For the current StratForge AI Center use tools/start-canonical-local.ps1; this script is not the normal startup path.'
$scriptDir = $PSScriptRoot
if (-not $scriptDir) { $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path }
if (-not $scriptDir) { $scriptDir = (Get-Location).Path }
$projectRoot = $scriptDir
Set-Location $projectRoot

function Read-BootstrapConfig {
    $path = Join-Path $projectRoot 'ai_lab\bootstrap.json'
    if (-not (Test-Path -LiteralPath $path)) { return @{} }
    try {
        $json = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
        $map = @{}
        $json.PSObject.Properties | ForEach-Object { $map[$_.Name] = [string]$_.Value }
        return $map
    } catch {
        Write-Host "[StratForge AI Lab] warning: cannot read ${path}: $_" -ForegroundColor Yellow
        return @{}
    }
}

function Resolve-FirstExisting([string[]]$Candidates) {
    foreach ($raw in $Candidates) {
        if ([string]::IsNullOrWhiteSpace($raw)) { continue }
        $expanded = [Environment]::ExpandEnvironmentVariables($raw)
        if (Test-Path -LiteralPath $expanded) { return $expanded }
    }
    return ''
}

function Test-ProcessName([string]$Needle) {
    try {
        $needleLower = $Needle.ToLowerInvariant()
        return [bool](Get-Process | Where-Object { $_.ProcessName.ToLowerInvariant().Contains($needleLower) } | Select-Object -First 1)
    } catch {
        return $false
    }
}

function Start-IfMissing([string]$Label, [string]$Needle, [string]$Exe) {
    if (Test-ProcessName $Needle) {
        Write-Host "[StratForge AI Lab] $Label already running." -ForegroundColor Cyan
        return
    }
    if ([string]::IsNullOrWhiteSpace($Exe)) {
        Write-Host "[StratForge AI Lab] $Label path is not configured; skipping auto-start." -ForegroundColor Yellow
        return
    }
    Write-Host "[StratForge AI Lab] starting ${Label}: $Exe" -ForegroundColor Cyan
    Start-Process -FilePath $Exe -WorkingDirectory (Split-Path -Parent $Exe) | Out-Null
}

function Resolve-LmsCli($Cfg) {
    if ($env:LMS_CLI -and (Test-Path -LiteralPath $env:LMS_CLI)) { return $env:LMS_CLI }
    if ($Cfg.ContainsKey('lms_cli') -and (Test-Path -LiteralPath $Cfg['lms_cli'])) { return $Cfg['lms_cli'] }
    $cmd = Get-Command lms -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return ''
}

function Invoke-Lms([string]$Cli, [string[]]$LmsArgs) {
    if ([string]::IsNullOrWhiteSpace($Cli)) { return $false }
    Write-Host "[StratForge AI Lab] lms $($LmsArgs -join ' ')" -ForegroundColor DarkCyan
    & $Cli @LmsArgs
    return ($LASTEXITCODE -eq 0)
}

function Wait-LmStudioModels([int]$TimeoutSec = 90) {
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        try {
            $resp = Invoke-RestMethod -Uri 'http://127.0.0.1:1234/v1/models' -TimeoutSec 5
            $count = @($resp.data).Count
            Write-Host "[StratForge AI Lab] LM Studio server responding; models listed: $count" -ForegroundColor Green
            return $true
        } catch {
            Start-Sleep -Seconds 3
        }
    }
    Write-Host "[StratForge AI Lab] LM Studio server did not answer on 127.0.0.1:1234 within timeout." -ForegroundColor Yellow
    return $false
}

$cfg = Read-BootstrapConfig
$ntExe = Resolve-FirstExisting @(
    $env:NINJATRADER_EXE,
    $(if ($cfg.ContainsKey('ninjatrader_exe')) { $cfg['ninjatrader_exe'] } else { '' }),
    'C:\Program Files\NinjaTrader 8\bin64\NinjaTrader.exe',
    'C:\Program Files\NinjaTrader 8\bin\NinjaTrader.exe',
    'C:\Program Files (x86)\NinjaTrader 8\bin64\NinjaTrader.exe',
    'C:\Program Files (x86)\NinjaTrader 8\bin\NinjaTrader.exe'
)
$lmExe = Resolve-FirstExisting @(
    $env:LM_STUDIO_EXE,
    $(if ($cfg.ContainsKey('lm_studio_exe')) { $cfg['lm_studio_exe'] } else { '' }),
    "$env:LOCALAPPDATA\Programs\LM Studio\LM Studio.exe",
    "$env:USERPROFILE\AppData\Local\Programs\LM Studio\LM Studio.exe"
)
$lms = Resolve-LmsCli $cfg

if (-not $SkipDependencyStart) {
    if ($StartNinjaTrader) {
        Write-Host '[StratForge AI Lab] StartNinjaTrader requested — launching NT (owner must sign in manually).' -ForegroundColor Yellow
        Start-IfMissing 'NinjaTrader' 'ninjatrader' $ntExe
    } else {
        Write-Host '[StratForge AI Lab] NinjaTrader auto-start skipped (default). Start NT yourself after login.' -ForegroundColor Cyan
    }
    Start-IfMissing 'LM Studio' 'lm studio' $lmExe
    Start-Sleep -Seconds 3

    if ($lms) {
        Invoke-Lms $lms @('server', 'start') | Out-Null
    } else {
        Write-Host '[StratForge AI Lab] lms CLI not found; backend bootstrap/readiness will report what is missing.' -ForegroundColor Yellow
    }

    Wait-LmStudioModels 90 | Out-Null
}

$env:AI_LAB_AUTO_BOOTSTRAP = '1'
$env:AI_LAB_LAZY_LM_STUDIO = '1'
$env:AI_LAB_AUTO_UNLOAD_MODELS = '1'
$env:AI_LAB_UNLOAD_AFTER_EACH_REQUEST = '1'
$env:AI_LAB_AUTO_STOP_LM_SERVER = '1'
& (Join-Path $projectRoot 'start.ps1') -Port $Port -UiPath '/ui/ai-lab.html' -NoBrowser:$NoBrowser
