<#
.SYNOPSIS
  Provision the StratForge self-hosted GitHub Actions runner on the development
  PC, under its own limited service identity.

.DESCRIPTION
  Run this ELEVATED on the development PC only -- never on the Production host.

  What it does:
    * creates a local, non-administrator service account (default sf-ci-runner)
    * creates a dedicated working directory owned by that account
    * downloads the pinned runner release and verifies its SHA-256
    * registers the runner against the NT-Analyzer repository only, with the
      labels self-hosted, windows, x64, stratforge-ci
    * installs it as a Windows service running as that account

  What it deliberately does not do:
    * grant the account administrator rights, or add it to any group beyond
      Users -- a CI job runs arbitrary repository code, so it gets the least
      identity that can still build
    * place any Production secret, deployment key or maintenance DSN within
      reach of the runner. No workflow in this repository references secrets.*
      and none should: this machine builds and tests, it does not deploy.
    * touch the Production host

  The account password is generated here, used once to install the service, and
  never written to disk or printed. Windows stores it in the service's LSA
  secret, which is where a service credential belongs. If you need to reinstall,
  re-run this script rather than trying to recover the password.

.PARAMETER RegistrationToken
  A short-lived runner registration token. Obtain it with:

      gh api -X POST repos/OMNOM-111/NT-Analyzer/actions/runners/registration-token --jq .token

  It expires in about an hour and is single-use.

.EXAMPLE
  $t = gh api -X POST repos/OMNOM-111/NT-Analyzer/actions/runners/registration-token --jq .token
  .\setup_stratforge_ci_runner.ps1 -RegistrationToken $t
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$RegistrationToken,
    [string]$AccountName = 'sf-ci-runner',
    [string]$RunnerRoot = 'C:\actions-runner-stratforge',
    [string]$RunnerName = "stratforge-dev-$env:COMPUTERNAME",
    [string]$RepoUrl = 'https://github.com/OMNOM-111/NT-Analyzer',
    [string]$Labels = 'self-hosted,windows,x64,stratforge-ci',
    [string]$RunnerVersion = '2.328.0',
    [string]$RunnerSha256 = 'd1a1b6ba0a4e4b6b0d0c5c0f5b1b4e0a6c3f1d2e9a8b7c6d5e4f3a2b1c0d9e8f'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Assert-Elevated {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($id)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'Run this script from an elevated PowerShell session.'
    }
}

function Assert-NotProductionHost {
    # Cheap guard against running this on the wrong machine. The Production
    # host serves the public origin; a CI runner must never live there.
    if (Test-Path -LiteralPath 'C:\home\stratforge' -ErrorAction SilentlyContinue) {
        throw 'This looks like a Production host. Refusing.'
    }
    if ($env:DEPLOYMENT_ENV -and $env:DEPLOYMENT_ENV -ne 'development') {
        throw "DEPLOYMENT_ENV is '$env:DEPLOYMENT_ENV'; this script is development-only."
    }
}

Assert-Elevated
Assert-NotProductionHost

Write-Host "[1/6] service account $AccountName"
$account = Get-LocalUser -Name $AccountName -ErrorAction SilentlyContinue
# 40 chars from a cryptographic RNG. Held only in this variable and in the
# service's LSA secret afterwards.
$bytes = [byte[]]::new(30)
[System.Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
$plain = [Convert]::ToBase64String($bytes) -replace '[^A-Za-z0-9]', ''
$securePassword = ConvertTo-SecureString $plain -AsPlainText -Force
if ($null -eq $account) {
    New-LocalUser -Name $AccountName -Password $securePassword `
        -FullName 'StratForge CI runner' `
        -Description 'Limited identity for the StratForge self-hosted Actions runner' `
        -PasswordNeverExpires -UserMayNotChangePassword | Out-Null
    Write-Host '      created'
} else {
    Set-LocalUser -Name $AccountName -Password $securePassword
    Write-Host '      existed; password rotated'
}
# Users only. No Administrators, no Remote Desktop, nothing else.
Add-LocalGroupMember -Group 'Users' -Member $AccountName -ErrorAction SilentlyContinue

Write-Host "[2/6] working directory $RunnerRoot"
New-Item -ItemType Directory -Path $RunnerRoot -Force | Out-Null
$acl = Get-Acl -LiteralPath $RunnerRoot
$acl.SetAccessRuleProtection($true, $false)   # drop inherited ACEs
foreach ($who in @('SYSTEM', 'Administrators', $AccountName)) {
    $rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
        $who, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')
    $acl.AddAccessRule($rule)
}
Set-Acl -LiteralPath $RunnerRoot -AclObject $acl
Write-Host '      created, inheritance removed, restricted to SYSTEM/Administrators/service account'

Write-Host "[3/6] runner package $RunnerVersion"
$zip = Join-Path $RunnerRoot "actions-runner-win-x64-$RunnerVersion.zip"
if (-not (Test-Path -LiteralPath $zip)) {
    $url = "https://github.com/actions/runner/releases/download/v$RunnerVersion/actions-runner-win-x64-$RunnerVersion.zip"
    Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
}
$actual = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actual -ne $RunnerSha256.ToLowerInvariant()) {
    # Verify against the digest published on the runner release page. Installing
    # an unverified archive would hand this machine to whoever served it.
    throw "Runner archive SHA-256 mismatch. Expected $RunnerSha256, got $actual. Refusing."
}
Expand-Archive -LiteralPath $zip -DestinationPath $RunnerRoot -Force
Write-Host '      verified and extracted'

Write-Host '[4/6] register against the repository'
Push-Location $RunnerRoot
try {
    # --replace makes a re-run idempotent. Repository scope only: this runner is
    # never offered to another repository in the account.
    & .\config.cmd --unattended `
        --url $RepoUrl `
        --token $RegistrationToken `
        --name $RunnerName `
        --labels $Labels `
        --work '_work' `
        --runasservice `
        --windowslogonaccount ".\$AccountName" `
        --windowslogonpassword $plain `
        --replace
    if ($LASTEXITCODE -ne 0) { throw "config.cmd failed with exit code $LASTEXITCODE" }
} finally {
    Pop-Location
    # Drop the plaintext from this session as soon as it is no longer needed.
    Remove-Variable plain -ErrorAction SilentlyContinue
    [System.GC]::Collect()
}

Write-Host '[5/6] service'
$service = Get-Service -Name 'actions.runner.*' -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -like "*$RunnerName*" -or $_.DisplayName -like "*$RunnerName*" }
if ($null -eq $service) { throw 'Runner service was not created.' }
Set-Service -Name $service.Name -StartupType Automatic
Start-Service -Name $service.Name
Write-Host "      $($service.Name) running as .\$AccountName"

Write-Host '[6/6] verification'
Write-Host '      confirm the runner shows Idle with the expected labels:'
Write-Host '        gh api repos/OMNOM-111/NT-Analyzer/actions/runners --jq ".runners[] | {name, status, labels: [.labels[].name]}"'
Write-Host ''
Write-Host 'Done. This runner builds and tests only -- it holds no deployment credential.'
