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
    [string]$RunnerVersion = '2.336.0',
    # Published by GitHub in the v2.336.0 release notes as the win-x64 digest.
    [string]$RunnerSha256 = 'd59123a43003e357b0805b5d0f611d0bd2f65ab67d51bd070dd4e7a0f685c162'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# Windows PowerShell 5.1 sits on .NET Framework, which on some configurations
# still defaults to TLS 1.0. github.com refuses that, and the failure surfaces
# as an opaque "connection closed" during download.
[Net.ServicePointManager]::SecurityProtocol =
    [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

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

function New-ServicePassword {
    <#
      Windows PowerShell 5.1 runs on .NET Framework, where
      RandomNumberGenerator has no static Fill() -- that is .NET Core / 5+ only.
      Create() + GetBytes() exists on both, so this works on 5.1 and 7 alike.

      The character classes are placed deliberately rather than hoped for: a
      local password policy can require upper, lower and digit, and a draw that
      happened to lack one would fail account creation intermittently, which is
      the worst kind of bug to chase. Ambiguous glyphs (O/0, I/l/1) are left out
      because this password may have to be read by a human during recovery.
    #>
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $upper = [char[]]'ABCDEFGHJKLMNPQRSTUVWXYZ'
        $lower = [char[]]'abcdefghijkmnopqrstuvwxyz'
        $digit = [char[]]'23456789'
        $all = $upper + $lower + $digit
        $length = 40
        $bytes = New-Object 'System.Byte[]' $length
        $rng.GetBytes($bytes)
        $chars = New-Object 'System.Collections.Generic.List[char]'
        $chars.Add($upper[$bytes[0] % $upper.Length])
        $chars.Add($lower[$bytes[1] % $lower.Length])
        $chars.Add($digit[$bytes[2] % $digit.Length])
        for ($i = 3; $i -lt $length; $i++) { $chars.Add($all[$bytes[$i] % $all.Length]) }
        # Fisher-Yates with RNG bytes, so the guaranteed classes do not always
        # sit in the first three positions.
        $swap = New-Object 'System.Byte[]' $length
        $rng.GetBytes($swap)
        for ($i = $chars.Count - 1; $i -gt 0; $i--) {
            $j = $swap[$i] % ($i + 1)
            $tmp = $chars[$i]; $chars[$i] = $chars[$j]; $chars[$j] = $tmp
        }
        return -join $chars
    } finally {
        $rng.Dispose()
    }
}

Write-Host "[1/6] service account $AccountName"
$account = Get-LocalUser -Name $AccountName -ErrorAction SilentlyContinue
# Held only in this variable and, after installation, in the service's LSA
# secret. Never written to disk, never printed.
$plain = New-ServicePassword
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
    # An interrupted earlier run leaves a truncated file. Re-fetch once rather
    # than making the operator clear it by hand; a second mismatch is real.
    Write-Host '      digest mismatch on the cached archive; re-downloading once'
    Remove-Item -LiteralPath $zip -Force
    $url = "https://github.com/actions/runner/releases/download/v$RunnerVersion/actions-runner-win-x64-$RunnerVersion.zip"
    Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
    $actual = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant()
}
if ($actual -ne $RunnerSha256.ToLowerInvariant()) {
    # Verify against the digest GitHub publishes. Installing an unverified
    # archive would hand this machine to whoever served it.
    throw "Runner archive SHA-256 mismatch. Expected $RunnerSha256, got $actual. Refusing."
}
Expand-Archive -LiteralPath $zip -DestinationPath $RunnerRoot -Force
Write-Host '      verified and extracted'

Write-Host '[4/6] register against the repository'
# A previous partial run can leave a service running and a .runner file behind.
# config.cmd will not reconfigure underneath a live service, so stand it down
# first; --replace then takes over the registration cleanly.
$existing = Get-Service -Name 'actions.runner.*' -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -like "*$RunnerName*" -or $_.DisplayName -like "*$RunnerName*" }
foreach ($svc in @($existing)) {
    if ($null -ne $svc -and $svc.Status -ne 'Stopped') {
        Write-Host "      stopping existing $($svc.Name) from an earlier run"
        Stop-Service -Name $svc.Name -Force -ErrorAction SilentlyContinue
    }
}
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
# Restart on failure instead of staying dead: a runner that died overnight
# would silently stop gating merges, which is worse than a noisy failure.
& sc.exe failure $service.Name reset= 86400 actions= restart/30000/restart/60000/restart/120000 | Out-Null
& sc.exe failureflag $service.Name 1 | Out-Null
Start-Service -Name $service.Name
Write-Host "      $($service.Name) running as .\$AccountName, auto-start + restart-on-failure"

Write-Host '[6/6] verification'
Write-Host '      confirm the runner shows Idle with the expected labels:'
Write-Host '        gh api repos/OMNOM-111/NT-Analyzer/actions/runners --jq ".runners[] | {name, status, labels: [.labels[].name]}"'
Write-Host ''
Write-Host 'Done. This runner builds and tests only -- it holds no deployment credential.'
