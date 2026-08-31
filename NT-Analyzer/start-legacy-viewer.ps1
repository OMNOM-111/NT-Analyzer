<#
.SYNOPSIS
    Starts the isolated read-only StratForge Legacy Viewer.
#>
[CmdletBinding()]
param(
    [int]$Port = 8876,
    [string]$SourceDataRoot = '',
    [string]$SnapshotRoot = '',
    [switch]$RefreshSnapshot,
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
if (-not $SourceDataRoot) { $SourceDataRoot = Join-Path $projectRoot 'data' }
if (-not $SnapshotRoot) {
    if (-not $env:LOCALAPPDATA) { throw 'LOCALAPPDATA is required for the isolated snapshot.' }
    $SnapshotRoot = Join-Path $env:LOCALAPPDATA 'StratForge\LegacyViewer'
}

$source = [IO.Path]::GetFullPath($SourceDataRoot)
$snapshotBase = [IO.Path]::GetFullPath($SnapshotRoot)
$snapshotData = Join-Path $snapshotBase 'data'
if (-not (Test-Path -LiteralPath $source -PathType Container)) {
    throw "Legacy source data root does not exist: $source"
}
if ($snapshotBase.TrimEnd('\').Equals($source.TrimEnd('\'), [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Legacy snapshot root must differ from the current data root.'
}
if ($snapshotBase.StartsWith($source.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Legacy snapshot root cannot be inside the current data root.'
}

$statusUrl = "http://127.0.0.1:$Port/api/legacy-viewer/status"
try {
    $running = Invoke-RestMethod -Uri $statusUrl -TimeoutSec 2 -ErrorAction Stop
    if ($running.mode -eq 'legacy_viewer') {
        if (-not $NoBrowser) { Start-Process "http://127.0.0.1:$Port/ui/" | Out-Null }
        Write-Host "Legacy Viewer is already running on port $Port." -ForegroundColor Cyan
        exit 0
    }
} catch { }

if ($RefreshSnapshot -or -not (Test-Path -LiteralPath $snapshotData -PathType Container)) {
    New-Item -ItemType Directory -Force -Path $snapshotData | Out-Null
    Write-Host "Creating isolated legacy snapshot from $source" -ForegroundColor Cyan
    & robocopy.exe $source $snapshotData /E /COPY:DAT /DCOPY:DAT /R:1 /W:1 /NFL /NDL /NJH /NJS /NP
    if ($LASTEXITCODE -gt 7) { throw "Snapshot copy failed with robocopy exit code $LASTEXITCODE." }
}

$env:DEPLOYMENT_ENV = 'development'
$env:STRATFORGE_ENV = 'development'
$env:STRATFORGE_LEGACY_VIEWER = '1'
$env:STRATFORGE_DEVELOPMENT_DATA_ROOT = $snapshotData
$env:STRATFORGE_BIND_HOST = '127.0.0.1'
$env:STRATFORGE_ALLOWED_HOSTS = '127.0.0.1,localhost'
$env:STRATFORGE_INSTANCE_ID = "stratforge-legacy-viewer-$($env:COMPUTERNAME)"
$env:STRATFORGE_DEPLOYMENT_ROLE = 'api'
$env:STRATFORGE_CONFIG_PROFILE = 'legacy-viewer-read-only'
$env:STRATFORGE_DATABASE_ID = 'legacy-viewer-snapshot'
$env:STRATFORGE_QUEUE_ID = 'legacy-viewer-disabled'
$env:STRATFORGE_OBJECT_STORAGE_ID = 'legacy-viewer-snapshot'
$env:STRATFORGE_TELEGRAM_BOT_ID = 'legacy-viewer-disabled'
$env:STRATFORGE_COOKIE_NAMESPACE = 'sf-legacy-viewer'
$env:STRATFORGE_SIGNING_KEY_ID = 'legacy-viewer-local'
$env:STRATFORGE_LOG_NAMESPACE = 'legacy-viewer'
$env:STRATFORGE_LIVE_TRADING_ALLOWED = '0'
$env:STRATFORGE_REAL_PAYMENTS_ALLOWED = '0'
$env:NTA_TEST_BYPASS_AUTH = '1'
$env:NTA_ENABLE_TEST_AUTH = '0'
$env:NTA_ENABLE_IMPERSONATION = '0'

$python = (Get-Command python -ErrorAction Stop).Source
$child = Start-Process -FilePath $python -ArgumentList @('-m', 'app.legacy_viewer', [string]$Port) -WorkingDirectory $projectRoot -PassThru -NoNewWindow
try {
    $ready = $false
    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        if ($child.HasExited) { throw "Legacy Viewer exited with code $($child.ExitCode)." }
        Start-Sleep -Milliseconds 250
        try {
            $status = Invoke-RestMethod -Uri $statusUrl -TimeoutSec 2 -ErrorAction Stop
            if ($status.mode -eq 'legacy_viewer' -and $status.read_only) { $ready = $true; break }
        } catch { }
    }
    if (-not $ready) { throw 'Legacy Viewer did not become ready.' }
    $url = "http://127.0.0.1:$Port/ui/"
    Write-Host "Legacy Viewer: $url" -ForegroundColor Green
    Write-Host "Snapshot: $snapshotData" -ForegroundColor DarkGray
    if (-not $NoBrowser) { Start-Process $url | Out-Null }
    Wait-Process -Id $child.Id
} finally {
    if (-not $child.HasExited) { Stop-Process -Id $child.Id -Force }
}
