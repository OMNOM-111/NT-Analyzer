<#
.SYNOPSIS
    Create a Windows desktop shortcut that runs 00_START_AI_LAB.cmd.
#>
[CmdletBinding()]
param(
    [string]$ShortcutName = 'NT-Analyzer AI Lab'
)
$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
if (-not $projectRoot) { $projectRoot = (Get-Location).Path }

$target = Join-Path $projectRoot '00_START_AI_LAB.cmd'
if (-not (Test-Path $target)) { throw "Missing target: $target" }

$desktop = [Environment]::GetFolderPath('Desktop')
$lnkPath = Join-Path $desktop "$ShortcutName.lnk"

$wsh = New-Object -ComObject WScript.Shell
$lnk = $wsh.CreateShortcut($lnkPath)
$lnk.TargetPath = $target
$lnk.WorkingDirectory = $projectRoot
$lnk.Description = 'Launch NT-Analyzer AI Strategy Lab stack'
$lnk.IconLocation = "$env:WINDIR\System32\shell32.dll,167"
$lnk.Save()

Write-Host "Shortcut created: $lnkPath" -ForegroundColor Green
