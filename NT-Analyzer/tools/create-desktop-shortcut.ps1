<#
.SYNOPSIS
    Create a Windows desktop shortcut that runs 00_START_NT_ANALYZER.cmd.

.DESCRIPTION
    No admin needed. Idempotent: re-creates the shortcut if it already exists.
#>
[CmdletBinding()]
param(
    [string]$ShortcutName = 'StratForge AI'
)
$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
if (-not $projectRoot) { $projectRoot = (Get-Location).Path }

$target  = Join-Path $projectRoot '00_START_NT_ANALYZER.cmd'
if (-not (Test-Path $target)) { throw "Missing target: $target" }

$desktop = [Environment]::GetFolderPath('Desktop')
$lnkPath = Join-Path $desktop "$ShortcutName.lnk"
$legacyLnkPath = Join-Path $desktop 'NT-Analyzer.lnk'
$brandIcon = Join-Path $projectRoot 'app\static\brand\stratforge-icon.ico'

if ((Test-Path -LiteralPath $legacyLnkPath) -and -not (Test-Path -LiteralPath $lnkPath)) {
    Move-Item -LiteralPath $legacyLnkPath -Destination $lnkPath -Force
}
if (-not (Test-Path -LiteralPath $brandIcon)) { throw "Missing brand icon: $brandIcon" }

$wsh = New-Object -ComObject WScript.Shell
$lnk = $wsh.CreateShortcut($lnkPath)
$lnk.TargetPath       = $target
$lnk.WorkingDirectory = $projectRoot
$lnk.Description      = 'Launch StratForge AI (local backend + UI)'
$lnk.IconLocation     = "$brandIcon,0"
$lnk.Save()

Write-Host "Shortcut created: $lnkPath" -ForegroundColor Green
