<#
.SYNOPSIS
    Manual compatibility launcher for the persistent Vitek supervisor.

.DESCRIPTION
    Starts the same Python supervisor used by Task Scheduler. The installer now
    registers Python directly so administrative stop controls the real supervisor
    process; this wrapper remains useful for an interactive/manual launch.
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

$python = Resolve-Python
if (-not $python) {
    throw 'Python 3 not found; Task Scheduler will retry the supervisor.'
}

# Python owns the child process so it can persist the exact exit code, stderr
# tail, restart count and crash-loop safe mode. The scheduled installation uses
# a direct Python action; this PowerShell path is only a manual compatibility UI.
if ($python -eq 'py') {
    & $python -3 -m app.backend_supervisor --development-profile --port $Port --retry-seconds $RetrySeconds
} else {
    & $python -m app.backend_supervisor --development-profile --port $Port --retry-seconds $RetrySeconds
}
exit $LASTEXITCODE
