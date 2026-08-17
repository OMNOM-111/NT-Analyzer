<#
.SYNOPSIS
    StratForge AI launcher.

.DESCRIPTION
    Starts the local Python backend (which also serves the static UI) on
    127.0.0.1:<auto port>, opens the default browser at /ui/, and on
    Ctrl+C / window close kills the backend cleanly.

    Does NOT start NinjaTrader 8. The UI explicitly tells the operator
    when NinjaTrader is not running.

.PARAMETER Port
    Optional preferred port. If busy, server picks the next free one.
#>
[CmdletBinding()]
param(
    [int]$Port = 8765,
    [string]$UiPath = '/ui/',
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
# start.ps1 lives directly in the StratForge AI project root.
$scriptDir = $PSScriptRoot
if (-not $scriptDir) { $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path }
if (-not $scriptDir) { $scriptDir = (Get-Location).Path }
$projectRoot = $scriptDir
Set-Location $projectRoot
if (-not $UiPath.StartsWith('/')) { $UiPath = '/' + $UiPath }

# This launcher is intentionally Development-only.  It preserves the existing
# local data directory while reserving a distinct unused production root, so a
# future production profile cannot be selected by an omitted variable.
$requestedEnvironment = if ($env:DEPLOYMENT_ENV) { $env:DEPLOYMENT_ENV } elseif ($env:STRATFORGE_ENV) { $env:STRATFORGE_ENV } else { 'development' }
if ($requestedEnvironment -notin @('development', 'dev', 'local')) {
    Write-Host "ERROR: start.ps1 is Development-only; DEPLOYMENT_ENV=$requestedEnvironment" -ForegroundColor Red
    exit 2
}
$env:DEPLOYMENT_ENV = 'development'
$env:STRATFORGE_ENV = 'development'
if (-not $env:STRATFORGE_INSTANCE_ID) {
    $env:STRATFORGE_INSTANCE_ID = "stratforge-dev-$($env:COMPUTERNAME)"
}
if (-not $env:STRATFORGE_DEPLOYMENT_ROLE) { $env:STRATFORGE_DEPLOYMENT_ROLE = 'all-in-one' }
if (-not $env:STRATFORGE_CONFIG_PROFILE) { $env:STRATFORGE_CONFIG_PROFILE = 'local-development' }

# Environment-registry signing key, if this machine has been enrolled as the
# development publisher.  The file is git-ignored and holds nothing but the key
# and the peer list; absent, LOCAL simply does not publish and every other
# feature works unchanged.  Values are never echoed.
$registryKeyFile = Join-Path $projectRoot 'data\secrets\environment-registry.env'
if (Test-Path -LiteralPath $registryKeyFile) {
    foreach ($line in Get-Content -LiteralPath $registryKeyFile -Encoding UTF8) {
        $entry = $line.Trim()
        if (-not $entry -or $entry.StartsWith('#') -or -not $entry.Contains('=')) { continue }
        $name = $entry.Substring(0, $entry.IndexOf('=')).Trim()
        $value = $entry.Substring($entry.IndexOf('=') + 1).Trim()
        # The file is written for POSIX `set -a`, so values are single-quoted.
        if ($value.Length -ge 2 -and $value[0] -eq "'" -and $value[-1] -eq "'") {
            $value = $value.Substring(1, $value.Length - 2)
        }
        if ($name) { Set-Item -Path "Env:$name" -Value $value }
    }
    Write-Host "Environment registry: development publisher key loaded." -ForegroundColor DarkGray
}
$versionFile = Join-Path $projectRoot 'VERSION.json'
if (-not (Test-Path -LiteralPath $versionFile)) {
    Write-Host "ERROR: project version file not found: $versionFile" -ForegroundColor Red
    exit 2
}
try { $projectVersion = Get-Content -LiteralPath $versionFile -Raw -Encoding UTF8 | ConvertFrom-Json }
catch {
    Write-Host "ERROR: VERSION.json is invalid: $($_.Exception.Message)" -ForegroundColor Red
    exit 2
}
# VERSION.json may describe the next release candidate (for example channel=beta
# while 0.10.0-beta.1 is being prepared). This launcher is still Development:
# it always forces RELEASE_CHANNEL=dev and must not refuse to start just because
# the product version file was stamped for a Canary/Production cut.
# Never inherit a beta/stable identity from another terminal.  This launcher
# is the one authoritative way to start the checked-out Development build.
$env:APP_VERSION = [string]$projectVersion.version
$env:STRATFORGE_BUILD_VERSION = [string]$projectVersion.version
$env:STRATFORGE_BUILD_DATE = [string]$projectVersion.build_date
# Windows PowerShell/ConvertFrom-Json may materialize an ISO JSON string as a
# DateTime. Casting that object to [string] uses the current locale
# (e.g. 08/02/2026 01:35:50), which is no longer ISO-8601 and makes the backend
# correctly fail closed. Preserve the canonical UTC identity across shells.
$buildTimestampValue = $projectVersion.build_timestamp_utc
if ($buildTimestampValue -is [DateTime]) {
    $env:BUILD_TIMESTAMP_UTC = $buildTimestampValue.ToUniversalTime().ToString(
        'yyyy-MM-ddTHH:mm:ssZ', [Globalization.CultureInfo]::InvariantCulture
    )
} else {
    $env:BUILD_TIMESTAMP_UTC = [string]$buildTimestampValue
}
$env:STRATFORGE_BUILD_TIMESTAMP_UTC = $env:BUILD_TIMESTAMP_UTC
$env:RELEASE_CHANNEL = 'dev'
$env:STRATFORGE_RELEASE_CHANNEL = 'dev'
$gitSha = (& git rev-parse HEAD 2>$null | Select-Object -First 1)
if (-not $gitSha -or $gitSha -notmatch '^[0-9a-fA-F]{40}([0-9a-fA-F]{24})?$') {
    Write-Host 'ERROR: the local launcher cannot resolve a full Git commit SHA.' -ForegroundColor Red
    exit 2
}
$gitDirty = [bool](& git status --porcelain 2>$null)
$env:GIT_COMMIT_SHA = [string]$gitSha
$env:STRATFORGE_GIT_COMMIT_SHA = $env:GIT_COMMIT_SHA
$env:BUILD_ID = "dev-$($env:APP_VERSION)-$($env:GIT_COMMIT_SHA.Substring(0, 12))"
$env:STRATFORGE_BUILD_ID = $env:BUILD_ID
$env:DIRTY = if ($gitDirty) { '1' } else { '0' }
$env:STRATFORGE_BUILD_DIRTY = $env:DIRTY
Remove-Item Env:ARTIFACT_SHA256 -ErrorAction SilentlyContinue
Remove-Item Env:STRATFORGE_ARTIFACT_SHA256 -ErrorAction SilentlyContinue
if (-not $env:STRATFORGE_REGION) { $env:STRATFORGE_REGION = 'local' }
if (-not $env:STRATFORGE_BIND_HOST) { $env:STRATFORGE_BIND_HOST = '127.0.0.1' }
if (-not $env:STRATFORGE_ALLOWED_HOSTS) { $env:STRATFORGE_ALLOWED_HOSTS = '127.0.0.1,localhost' }
if (-not $env:STRATFORGE_DEVELOPMENT_DATA_ROOT) {
    $env:STRATFORGE_DEVELOPMENT_DATA_ROOT = (Join-Path $projectRoot 'data')
}
if (-not $env:STRATFORGE_DATA_ROOT) {
    $env:STRATFORGE_DATA_ROOT = (Join-Path $projectRoot '.stratforge-production-data-disabled')
}
if (-not $env:STRATFORGE_DATABASE_ID) { $env:STRATFORGE_DATABASE_ID = 'development-sqlite' }
if (-not $env:STRATFORGE_QUEUE_ID) { $env:STRATFORGE_QUEUE_ID = 'development-local-worker' }
if (-not $env:STRATFORGE_OBJECT_STORAGE_ID) { $env:STRATFORGE_OBJECT_STORAGE_ID = 'development-files' }
if (-not $env:STRATFORGE_TELEGRAM_BOT_ID) { $env:STRATFORGE_TELEGRAM_BOT_ID = 'development-local' }
if (-not $env:STRATFORGE_COOKIE_NAMESPACE) { $env:STRATFORGE_COOKIE_NAMESPACE = 'sf-dev' }
if (-not $env:STRATFORGE_SIGNING_KEY_ID) { $env:STRATFORGE_SIGNING_KEY_ID = 'development-local' }
if (-not $env:STRATFORGE_LOG_NAMESPACE) { $env:STRATFORGE_LOG_NAMESPACE = 'development' }
if (-not $env:STRATFORGE_LIVE_TRADING_ALLOWED) { $env:STRATFORGE_LIVE_TRADING_ALLOWED = '0' }
if (-not $env:STRATFORGE_REAL_PAYMENTS_ALLOWED) { $env:STRATFORGE_REAL_PAYMENTS_ALLOWED = '0' }
if (-not $env:STRATFORGE_DEVELOPMENT_ORIGIN) { $env:STRATFORGE_DEVELOPMENT_ORIGIN = "http://127.0.0.1:$Port" }
if (-not $env:STRATFORGE_CANARY_ORIGIN) { $env:STRATFORGE_CANARY_ORIGIN = 'https://canary.stratforges.com' }
if (-not $env:STRATFORGE_PRODUCTION_ORIGIN) { $env:STRATFORGE_PRODUCTION_ORIGIN = 'https://app.stratforges.com' }

$serverScript = Join-Path $projectRoot 'app\server.py'
if (-not (Test-Path -LiteralPath $serverScript)) {
    Write-Host "ERROR: backend entrypoint not found at: $serverScript" -ForegroundColor Red
    Write-Host "       expected this script (start.ps1) to live in the StratForge AI project root." -ForegroundColor Red
    Write-Host "       resolved project_root = $projectRoot" -ForegroundColor Red
    exit 2
}

# Pick python launcher.
$pyCmd = $null
foreach ($c in 'py','python','python3') {
    & $c --version 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { $pyCmd = $c; break }
}
if (-not $pyCmd) {
    Write-Host 'ERROR: Python 3 is not installed or not on PATH.' -ForegroundColor Red
    Write-Host 'Install Python 3.10+ from https://www.python.org/downloads/ and re-run.'
    exit 1
}

Write-Host '[StratForge AI] starting backend...' -ForegroundColor Cyan
Write-Host "[StratForge AI] project_root: $projectRoot"
Write-Host "[StratForge AI] DEV | v$($env:APP_VERSION) | $($env:GIT_COMMIT_SHA.Substring(0, 7)) | dirty=$($env:DIRTY)" -ForegroundColor Yellow
Write-Host '[StratForge AI] This launcher never starts the stable Production service.' -ForegroundColor Yellow

$env:PYTHONUNBUFFERED = '1'
$env:NT_ANALYZER_ROOT = $projectRoot

# Spawn backend as a child process. Capture stdout so we can parse the URL.
# Build a single argument string (Windows PowerShell 5.1 / .NET Framework has
# no ProcessStartInfo.ArgumentList).
$argParts = @()
if ($pyCmd -eq 'py') { $argParts += '-3' }
$argParts += @('-m','app.server', "$Port")
$argString = ($argParts -join ' ')

$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $pyCmd
$psi.Arguments = $argString
$psi.WorkingDirectory = $projectRoot
$psi.UseShellExecute = $false
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError  = $true
$psi.CreateNoWindow = $true   # no extra console window for the backend process

# ---------------------------------------------------------------------------
# Check if something is already listening on the requested port.
# If so, skip starting a new backend: just open the browser and exit cleanly.
# ---------------------------------------------------------------------------
function Test-PortInUse([int]$p) {
    $tcp = [System.Net.Sockets.TcpClient]::new()
    try {
        $tcp.Connect('127.0.0.1', $p)
        return $true
    } catch {
        return $false
    } finally {
        $tcp.Dispose()
    }
}

if (Test-PortInUse $Port) {
    Write-Host "[StratForge AI] backend already running on port $Port." -ForegroundColor Cyan
    if (-not $NoBrowser) {
        $url = "http://127.0.0.1:$Port$UiPath"
        Write-Host "[StratForge AI] opening browser: $url"
        Start-Process $url | Out-Null
    }
    exit 0
}

$proc = [System.Diagnostics.Process]::Start($psi)
if (-not $proc) {
    Write-Host 'ERROR: failed to start backend' -ForegroundColor Red
    exit 1
}

# Stream backend stdout into our console so the user sees the bind URL.
$urlOpened = $false
$uiUrlRegex   = [regex]'http://127\.0\.0\.1:\d+/ui/'
$baseUrlRegex = [regex]'http://127\.0\.0\.1:\d+/'

# Kill backend on PowerShell exit (Ctrl+C / window close).
Register-EngineEvent PowerShell.Exiting -Action {
    try { if (-not $proc.HasExited) { $proc.Kill() } } catch {}
} | Out-Null

try {
    while (-not $proc.HasExited) {
        if ($proc.StandardOutput.Peek() -ge 0) {
            $line = $proc.StandardOutput.ReadLine()
            if ($null -ne $line) {
                Write-Host "[backend] $line"
                if (-not $urlOpened -and -not $NoBrowser) {
                    $m = $uiUrlRegex.Match($line)
                    if ($m.Success) {
                        $base = $m.Value -replace '/ui/$', ''
                        Start-Process ($base + $UiPath) | Out-Null
                        $urlOpened = $true
                    } else {
                        $m = $baseUrlRegex.Match($line)
                        if ($m.Success) {
                            Start-Process ($m.Value.TrimEnd('/') + $UiPath) | Out-Null
                            $urlOpened = $true
                        }
                    }
                    if ($urlOpened) {
                        Write-Host '[StratForge AI] browser opened.' -ForegroundColor Cyan
                    }
                }
            }
        } else {
            Start-Sleep -Milliseconds 100
        }
        if ($proc.StandardError.Peek() -ge 0) {
            $eline = $proc.StandardError.ReadLine()
            if ($null -ne $eline) { Write-Host "[backend][err] $eline" -ForegroundColor Yellow }
        }
    }
} finally {
    try { if (-not $proc.HasExited) { $proc.Kill() } } catch {}
}

$code = $proc.ExitCode
if ($code -ne 0) {
    Write-Host "[StratForge AI] backend exited with code $code." -ForegroundColor Yellow
} else {
    Write-Host '[StratForge AI] backend stopped.' -ForegroundColor Cyan
}
exit $code
