$ErrorActionPreference = 'Stop'
$launcher = Join-Path $PSScriptRoot 'launch_canonical_local.py'
& 'C:\Python312\python.exe' $launcher
if ($LASTEXITCODE -ne 0) {
    Write-Host 'Canonical Local startup failed. Review the source mismatch above.'
    Read-Host 'Press Enter to close'
}
exit $LASTEXITCODE
