<# Installs the per-user Vitek watchdog in Windows Task Scheduler. #>
[CmdletBinding()]
param(
    [string]$TaskName = 'StratForge Vitek',
    [int]$Port = 8765,
    [switch]$NoStart
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$python = $null
foreach ($candidate in 'python', 'python3', 'py') {
    try {
        if ($candidate -eq 'py') {
            $resolved = (& $candidate -3 -c 'import sys; print(sys.executable)' 2>$null | Select-Object -Last 1)
        } else {
            $resolved = (& $candidate -c 'import sys; print(sys.executable)' 2>$null | Select-Object -Last 1)
        }
        if ($LASTEXITCODE -eq 0 -and $resolved) {
            $python = [string]$resolved
            break
        }
    } catch {}
}
if (-not $python -or -not (Test-Path -LiteralPath $python)) {
    throw 'Python 3 executable not found; Vitek supervisor was not installed.'
}

$arguments = "-m app.backend_supervisor --port $Port --retry-seconds 10"
$action = New-ScheduledTaskAction -Execute $python -Argument $arguments -WorkingDirectory $projectRoot
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
    launcher = $python
    arguments = $arguments
    port = $Port
} | ConvertTo-Json | Set-Content -LiteralPath $markerPath -Encoding UTF8

if (-not $NoStart) { Start-ScheduledTask -TaskName $TaskName }
$task = Get-ScheduledTask -TaskName $TaskName
Write-Host "Vitek scheduled task installed: $($task.TaskName) [$($task.State)]" -ForegroundColor Green
Write-Host "The watchdog keeps monitoring active when the browser UI is closed." -ForegroundColor Cyan
