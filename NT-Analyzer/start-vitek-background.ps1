<#
.SYNOPSIS
    Persistent background watchdog for Vitek.

.DESCRIPTION
    Keeps the StratForge backend alive without opening a browser. If a normal
    desktop backend already owns the port, the watchdog waits. When that backend
    exits, the watchdog starts a replacement so Telegram, NinjaTrader monitoring
    and event-driven Vitek handling continues while the UI is closed.
#>
[CmdletBinding()]
param(
    [int]$Port = 8765,
    [int]$RetrySeconds = 10
)

$ErrorActionPreference = 'Continue'
$projectRoot = $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$utf8 = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = $utf8
$OutputEncoding = $utf8
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUNBUFFERED = '1'
$env:NT_ANALYZER_ROOT = $projectRoot
$env:NTA_VITEK_BACKGROUND = '1'

function Test-LocalPort([int]$Value) {
    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $connect = $client.BeginConnect('127.0.0.1', $Value, $null, $null)
        if (-not $connect.AsyncWaitHandle.WaitOne(800)) { return $false }
        $client.EndConnect($connect)
        return $true
    } catch {
        return $false
    } finally {
        $client.Dispose()
    }
}

function Resolve-Python {
    # Prefer the real interpreter.  Windows py.exe can exit after spawning a
    # child python.exe, which makes a watchdog track the launcher instead of
    # the backend process it is supposed to supervise.
    foreach ($candidate in 'python', 'python3', 'py') {
        try {
            & $candidate --version 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) { return $candidate }
        } catch {}
    }
    return $null
}

$logDir = Join-Path $projectRoot 'logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logPath = Join-Path $logDir 'vitek-background.log'

while ($true) {
    if (Test-LocalPort $Port) {
        Start-Sleep -Seconds ([Math]::Max(3, $RetrySeconds))
        continue
    }
    $python = Resolve-Python
    if (-not $python) {
        "$(Get-Date -Format o) Python 3 not found; retrying." | Out-File -LiteralPath $logPath -Append -Encoding utf8
        Start-Sleep -Seconds 60
        continue
    }
    "$(Get-Date -Format o) Starting Vitek backend on 127.0.0.1:$Port." | Out-File -LiteralPath $logPath -Append -Encoding utf8
    try {
        $stamp = Get-Date -Format 'yyyyMMddTHHmmssfff'
        $stdoutPath = Join-Path $logDir "vitek-backend-$stamp.stdout.log"
        $stderrPath = Join-Path $logDir "vitek-backend-$stamp.stderr.log"
        if ($python -eq 'py') {
            $arguments = @('-3', '-m', 'app.server', [string]$Port)
        } else {
            $arguments = @('-m', 'app.server', [string]$Port)
        }
        $backend = Start-Process -FilePath $python -ArgumentList $arguments `
            -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
        "$(Get-Date -Format o) Backend process started pid=$($backend.Id)." | Out-File -LiteralPath $logPath -Append -Encoding utf8
        $backend.WaitForExit()
        "$(Get-Date -Format o) Backend exited with code $($backend.ExitCode). Output: $stdoutPath; errors: $stderrPath." | Out-File -LiteralPath $logPath -Append -Encoding utf8
    } catch {
        "$(Get-Date -Format o) Backend launch failed: $($_.Exception.Message)" | Out-File -LiteralPath $logPath -Append -Encoding utf8
    }
    Start-Sleep -Seconds ([Math]::Max(3, $RetrySeconds))
}
