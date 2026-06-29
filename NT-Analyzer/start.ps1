<#
.SYNOPSIS
    NT-Analyzer launcher.

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
# start.ps1 lives directly in the NT-Analyzer project root.
$scriptDir = $PSScriptRoot
if (-not $scriptDir) { $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path }
if (-not $scriptDir) { $scriptDir = (Get-Location).Path }
$projectRoot = $scriptDir
Set-Location $projectRoot
if (-not $UiPath.StartsWith('/')) { $UiPath = '/' + $UiPath }

$serverScript = Join-Path $projectRoot 'app\server.py'
if (-not (Test-Path -LiteralPath $serverScript)) {
    Write-Host "ERROR: backend entrypoint not found at: $serverScript" -ForegroundColor Red
    Write-Host "       expected this script (start.ps1) to live in the NT-Analyzer project root." -ForegroundColor Red
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

Write-Host '[NT-Analyzer] starting backend...' -ForegroundColor Cyan
Write-Host "[NT-Analyzer] project_root: $projectRoot"

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
    Write-Host "[NT-Analyzer] backend already running on port $Port." -ForegroundColor Cyan
    if (-not $NoBrowser) {
        $url = "http://127.0.0.1:$Port$UiPath"
        Write-Host "[NT-Analyzer] opening browser: $url"
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
                        Write-Host '[NT-Analyzer] browser opened.' -ForegroundColor Cyan
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
    Write-Host "[NT-Analyzer] backend exited with code $code." -ForegroundColor Yellow
} else {
    Write-Host '[NT-Analyzer] backend stopped.' -ForegroundColor Cyan
}
exit $code
