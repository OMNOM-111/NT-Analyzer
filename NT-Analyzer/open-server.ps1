[CmdletBinding()]
param(
    [string]$Origin = 'https://app.stratforges.com',
    [string]$UiPath = '/ui/',
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
$statusUri = $Origin.TrimEnd('/') + '/api/runtime/env'
$uiUri = $Origin.TrimEnd('/') + '/' + $UiPath.TrimStart('/')

try {
    $status = Invoke-RestMethod -Uri $statusUri -Method Get -TimeoutSec 10 -Headers @{ Accept = 'application/json' }
} catch {
    Write-Host "ERROR: cannot verify the StratForge server identity at $statusUri" -ForegroundColor Red
    Write-Host 'The server was not opened because its version could not be verified.' -ForegroundColor Red
    exit 2
}

$deployment = if ($status.deployment) { $status.deployment } else { $status }
$channel = ([string]$deployment.release_channel).Trim().ToLowerInvariant()
$version = ([string]$deployment.build_version).Trim()
$buildDate = ([string]$deployment.build_date).Trim()
$labels = @{
    development = 'DEVELOPMENT / DEV'
    canary = 'PRE-RELEASE / CANARY'
    stable = 'READY / STABLE'
}
if (-not $labels.ContainsKey($channel) -or -not $version -or -not $buildDate) {
    Write-Host 'ERROR: the server returned an incomplete or unknown build identity.' -ForegroundColor Red
    exit 2
}

$label = $labels[$channel]
$color = if ($channel -eq 'stable') { 'Green' } elseif ($channel -eq 'canary') { 'Yellow' } else { 'Magenta' }
Write-Host "[StratForge AI] server: v$version | $label | from $buildDate" -ForegroundColor $color
if ($channel -ne 'stable') {
    Write-Host 'WARNING: this is not the stable release. The same status will be visible inside the application.' -ForegroundColor Yellow
}
if ($NoBrowser) {
    Write-Host "[StratForge AI] identity verified for $uiUri"
} else {
    Write-Host "[StratForge AI] opening $uiUri"
    Start-Process $uiUri | Out-Null
}
