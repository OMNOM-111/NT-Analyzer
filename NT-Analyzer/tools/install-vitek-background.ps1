<# Installs the per-user Vitek watchdog in Windows Task Scheduler. #>
[CmdletBinding()]
param(
    [string]$TaskName = 'StratForge Vitek',
    [int]$Port = 8765,
    [switch]$NoStart
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$launcher = Join-Path $projectRoot 'start-vitek-background.ps1'
if (-not (Test-Path -LiteralPath $launcher)) {
    throw "Vitek launcher not found: $launcher"
}

$powerShell = (Get-Command powershell.exe -ErrorAction Stop).Source
$escapedLauncher = $launcher.Replace('"', '""')
$arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$escapedLauncher`" -Port $Port"
$action = New-ScheduledTaskAction -Execute $powerShell -Argument $arguments -WorkingDirectory $projectRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Description 'Vitek duty controller for StratForge AI' -Force | Out-Null

$markerPath = Join-Path $projectRoot 'data\operations\vitek-background.json'
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $markerPath) | Out-Null
@{
    installed = $true
    task_name = $TaskName
    installed_at_utc = [DateTime]::UtcNow.ToString('o')
    launcher = $launcher
    port = $Port
} | ConvertTo-Json | Set-Content -LiteralPath $markerPath -Encoding UTF8

if (-not $NoStart) { Start-ScheduledTask -TaskName $TaskName }
$task = Get-ScheduledTask -TaskName $TaskName
Write-Host "Vitek scheduled task installed: $($task.TaskName) [$($task.State)]" -ForegroundColor Green
Write-Host "The watchdog keeps monitoring active when the browser UI is closed." -ForegroundColor Cyan
