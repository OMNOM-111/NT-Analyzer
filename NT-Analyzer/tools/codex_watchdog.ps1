[CmdletBinding()]
param(
    [int]$IntervalSeconds = 5,
    [switch]$Once,
    [switch]$NoDesktopWarning
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$workspaceRoot = Split-Path -Parent $projectRoot
$artifactRoot = Join-Path $projectRoot ".artifacts"
$logPath = Join-Path $artifactRoot "codex-watchdog.jsonl"
$latestPath = Join-Path $artifactRoot "codex-watchdog-latest.json"
$alertStatePath = Join-Path $artifactRoot "codex-watchdog-alerts.json"

New-Item -ItemType Directory -Path $artifactRoot -Force | Out-Null

function Get-CodexProcessState {
    $processes = @(Get-Process -Name "ChatGPT" -ErrorAction SilentlyContinue |
        Sort-Object StartTime)
    if ($processes.Count -eq 0) {
        return [ordered]@{ running = $false; root_pid = $null; started_at = $null; process_count = 0 }
    }

    $root = $processes[0]
    return [ordered]@{
        running = $true
        root_pid = $root.Id
        started_at = $root.StartTime.ToUniversalTime().ToString("o")
        process_count = $processes.Count
    }
}

function Get-PendingRebootState {
    $componentBased = Test-Path "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending"
    $windowsUpdate = Test-Path "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired"
    $sessionManager = Get-ItemProperty `
        -Path "HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager" `
        -ErrorAction SilentlyContinue
    $pendingRename = $null -ne $sessionManager.PendingFileRenameOperations
    return [ordered]@{
        pending = ($componentBased -or $windowsUpdate -or $pendingRename)
        component_based_servicing = $componentBased
        windows_update = $windowsUpdate
        pending_file_rename = $pendingRename
    }
}

function Get-GitState {
    $branch = (& git -C $workspaceRoot branch --show-current 2>$null)
    $head = (& git -C $workspaceRoot rev-parse HEAD 2>$null)
    $changes = @(& git -C $workspaceRoot status --porcelain=v1 2>$null)
    return [ordered]@{
        branch = if ($branch) { $branch.Trim() } else { $null }
        head = if ($head) { $head.Trim() } else { $null }
        changed_paths = @($changes).Count
    }
}

function Get-HostState {
    $os = Get-CimInstance Win32_OperatingSystem
    $drive = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='C:'"
    return [ordered]@{
        free_memory_gb = [math]::Round(($os.FreePhysicalMemory * 1KB) / 1GB, 2)
        free_disk_c_gb = [math]::Round($drive.FreeSpace / 1GB, 2)
    }
}

function Get-CodexPackageVersion {
    $package = Get-AppxPackage -Name "OpenAI.Codex" -ErrorAction SilentlyContinue |
        Sort-Object Version -Descending |
        Select-Object -First 1
    if ($null -eq $package) { return $null }
    return $package.Version.ToString()
}

function Read-AlertState {
    if (-not (Test-Path $alertStatePath)) { return @{} }
    try {
        $data = Get-Content -Raw $alertStatePath | ConvertFrom-Json -AsHashtable
        if ($null -eq $data) { return @{} }
        return $data
    } catch {
        return @{}
    }
}

function Write-AlertState([hashtable]$State) {
    $State | ConvertTo-Json -Depth 4 | Set-Content -Encoding utf8 $alertStatePath
}

function Show-DesktopWarning([string]$Key, [string]$Message, [hashtable]$AlertState) {
    if ($AlertState.ContainsKey($Key)) { return }
    $AlertState[$Key] = (Get-Date).ToUniversalTime().ToString("o")
    Write-AlertState $AlertState
    if ($NoDesktopWarning) { return }

    $msg = Get-Command "msg.exe" -ErrorAction SilentlyContinue
    if ($null -ne $msg -and $env:USERNAME) {
        & $msg.Source $env:USERNAME "StratForge/Codex watchdog: $Message" 2>$null | Out-Null
    }
}

$previousPackageVersion = Get-CodexPackageVersion
$previousRootPid = $null

do {
    try {
        $timestamp = (Get-Date).ToUniversalTime().ToString("o")
        $process = Get-CodexProcessState
        $reboot = Get-PendingRebootState
        $hostState = Get-HostState
        $git = Get-GitState
        $packageVersion = Get-CodexPackageVersion
        $alerts = Read-AlertState

        if ($reboot.pending) {
            Show-DesktopWarning "pending_reboot" "Windows reports a pending reboot. Commit/checkpoint immediately and postpone restart." $alerts
        }
        if ($hostState.free_memory_gb -lt 2) {
            Show-DesktopWarning "low_memory" "Free physical memory is below 2 GB. Commit/checkpoint immediately." $alerts
        }
        if ($hostState.free_disk_c_gb -lt 10) {
            Show-DesktopWarning "low_disk" "Free space on C: is below 10 GB. Commit/checkpoint immediately." $alerts
        }
        if ($previousPackageVersion -and $packageVersion -and $packageVersion -ne $previousPackageVersion) {
            Show-DesktopWarning "package_change_$packageVersion" "Codex package changed from $previousPackageVersion to $packageVersion. Save work before continuing." $alerts
        }
        if ($previousRootPid -and $process.running -and $process.root_pid -ne $previousRootPid) {
            Show-DesktopWarning "process_restart_$($process.root_pid)" "Codex process restarted (PID $previousRootPid -> $($process.root_pid)). Resume from the run-state checkpoint." $alerts
        }

        $record = [ordered]@{
            timestamp = $timestamp
            watchdog_pid = $PID
            codex = $process
            codex_package_version = $packageVersion
            pending_reboot = $reboot
            host = $hostState
            git = $git
        }
        $json = $record | ConvertTo-Json -Depth 8 -Compress
        Add-Content -Encoding utf8 -Path $logPath -Value $json
        $record | ConvertTo-Json -Depth 8 | Set-Content -Encoding utf8 $latestPath

        if ($process.running) { $previousRootPid = $process.root_pid }
        if ($packageVersion) { $previousPackageVersion = $packageVersion }
    } catch {
        $failure = [ordered]@{
            timestamp = (Get-Date).ToUniversalTime().ToString("o")
            watchdog_pid = $PID
            error = $_.Exception.Message
        } | ConvertTo-Json -Compress
        Add-Content -Encoding utf8 -Path $logPath -Value $failure
    }

    if (-not $Once) { Start-Sleep -Seconds ([math]::Max(1, $IntervalSeconds)) }
} while (-not $Once)
