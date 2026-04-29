<#
.SYNOPSIS
    Create a Windows desktop shortcut that runs 00_START_NT_ANALYZER.cmd.

.DESCRIPTION
    No admin needed. Idempotent: re-creates the shortcut if it already exists.
#>
[CmdletBinding()]
param(
    [string]$ShortcutName = 'NT-Analyzer'
)
$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
if (-not $projectRoot) { $projectRoot = (Get-Location).Path }

$target  = Join-Path $projectRoot '00_START_NT_ANALYZER.cmd'
if (-not (Test-Path $target)) { throw "Missing target: $target" }

$desktop = [Environment]::GetFolderPath('Desktop')
$lnkPath = Join-Path $desktop "$ShortcutName.lnk"

$wsh = New-Object -ComObject WScript.Shell
$lnk = $wsh.CreateShortcut($lnkPath)
$lnk.TargetPath       = $target
$lnk.WorkingDirectory = $projectRoot
$lnk.Description      = 'Launch NT-Analyzer (local backend + UI)'
$lnk.IconLocation     = "$env:WINDIR\System32\shell32.dll,167"
$lnk.Save()

Write-Host "Shortcut created: $lnkPath" -ForegroundColor Green
