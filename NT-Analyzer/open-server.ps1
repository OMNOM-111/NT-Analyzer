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
$environment = ([string]$(if ($deployment.deployment_environment) { $deployment.deployment_environment } else { $deployment.environment })).Trim().ToLowerInvariant()
$channel = ([string]$deployment.release_channel).Trim().ToLowerInvariant()
$version = ([string]$(if ($deployment.app_version) { $deployment.app_version } else { $deployment.build_version })).Trim()
$buildTimestamp = ([string]$deployment.build_timestamp_utc).Trim()
$buildId = ([string]$deployment.build_id).Trim()
$gitSha = ([string]$deployment.git_commit_sha).Trim()
$artifactSha = ([string]$deployment.artifact_sha256).Trim()
$dirty = [bool]$deployment.dirty
$identityKey = "$environment/$channel"
$labels = @{
    'development/dev' = 'DEV'
    'canary/beta' = 'CANARY'
    'canary/stable' = 'CANARY'
    'production/beta' = 'BETA'
    'production/stable' = ''
}
if (-not $labels.ContainsKey($identityKey) -or -not $version -or -not $buildTimestamp -or -not $buildId -or -not $gitSha) {
    Write-Host 'ERROR: the server returned an incomplete or unknown build identity.' -ForegroundColor Red
    exit 2
}
if ($environment -ne 'development' -and (-not $artifactSha -or $dirty)) {
    Write-Host 'ERROR: a remote deployment must expose a clean artifact checksum.' -ForegroundColor Red
    exit 2
}

$label = $labels[$identityKey]
$color = if ($identityKey -eq 'production/stable') { 'Green' } elseif ($environment -eq 'canary') { 'Yellow' } else { 'Magenta' }
$prefix = if ($label) { "$label | " } else { '' }
$dirtyLabel = if ($dirty) { ' | dirty' } else { '' }
Write-Host "[StratForge AI] server: $prefix v$version | $($gitSha.Substring(0, 7))$dirtyLabel" -ForegroundColor $color
Write-Host "[StratForge AI] build: $buildId | $buildTimestamp"
if ($identityKey -ne 'production/stable') {
    Write-Host 'WARNING: this is not the stable release. The same status will be visible inside the application.' -ForegroundColor Yellow
}
if ($NoBrowser) {
    Write-Host "[StratForge AI] identity verified for $uiUri"
} else {
    Write-Host "[StratForge AI] opening $uiUri"
    Start-Process $uiUri | Out-Null
}
