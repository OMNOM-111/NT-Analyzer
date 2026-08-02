<#
.SYNOPSIS
    Starts an HTTPS Cloudflare Tunnel to the localhost-only StratForge backend.
#>
[CmdletBinding()]
param(
    [int]$Port = 8765,
    [string]$TunnelName = 'stratforge',
    [string]$Config = "$HOME\.cloudflared\config.yml",
    [switch]$Quick
)

$ErrorActionPreference = 'Stop'
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$localCandidates = @(
    (Join-Path $scriptRoot 'tools\cloudflared\cloudflared.exe'),
    (Join-Path $scriptRoot 'tools\cloudflared.exe'),
    (Join-Path $scriptRoot 'bin\cloudflared.exe'),
    (Join-Path $scriptRoot 'cloudflared.exe')
)
$cloudflaredPath = ''
foreach ($candidate in $localCandidates) {
    if (Test-Path -LiteralPath $candidate) {
        $cloudflaredPath = $candidate
        break
    }
}
if (-not $cloudflaredPath) {
    $cloudflared = Get-Command cloudflared -ErrorAction SilentlyContinue
    if ($cloudflared) { $cloudflaredPath = $cloudflared.Source }
}
if (-not $cloudflaredPath) {
    throw "cloudflared.exe not found. Put it into '$scriptRoot\tools\cloudflared\cloudflared.exe' or install cloudflared on PATH."
}

$tcp = [System.Net.Sockets.TcpClient]::new()
try {
    $tcp.Connect('127.0.0.1', $Port)
} catch {
    throw "StratForge backend is not listening on 127.0.0.1:$Port. Start it first."
} finally {
    $tcp.Dispose()
}

if ($Quick) {
    Write-Host "Starting temporary HTTPS tunnel to http://127.0.0.1:$Port" -ForegroundColor Cyan
    & $cloudflaredPath tunnel --url "http://127.0.0.1:$Port"
    exit $LASTEXITCODE
}

if (-not (Test-Path -LiteralPath $Config)) {
    throw "Cloudflare Tunnel config not found: $Config"
}
Write-Host "Starting named tunnel '$TunnelName' using $Config" -ForegroundColor Cyan
& $cloudflaredPath tunnel --config $Config run $TunnelName
exit $LASTEXITCODE
