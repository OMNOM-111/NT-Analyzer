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
$cloudflared = Get-Command cloudflared -ErrorAction SilentlyContinue
if (-not $cloudflared) {
    throw 'cloudflared is not installed or not available on PATH.'
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
    & $cloudflared.Source tunnel --url "http://127.0.0.1:$Port"
    exit $LASTEXITCODE
}

if (-not (Test-Path -LiteralPath $Config)) {
    throw "Cloudflare Tunnel config not found: $Config"
}
Write-Host "Starting named tunnel '$TunnelName' using $Config" -ForegroundColor Cyan
& $cloudflared.Source tunnel --config $Config run $TunnelName
exit $LASTEXITCODE
